from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.repositories import application_count, get_job, upsert_user
from app.keyboards.job import cancel_application
from app.services.formatting import TZ, job_text
from app.services.job_service import apply_to_job
from app.services.job_service import cancel_application as cancel_app_service
from app.states.forms import WorkerNameForm

router = Router()


@router.callback_query(F.data.startswith("job:apply:"))
async def begin_apply(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    jid = int(call.data.rsplit(":", 1)[1])
    job = await get_job(session, jid)
    if not job:
        await call.answer("Работа не найдена", show_alert=True)
        return
    await state.update_data(job_id=jid)
    await state.set_state(WorkerNameForm.full_name)
    await call.message.answer("Отлично! Введите ваше имя и фамилию, например: Иван Иванов.")
    await call.answer()


@router.message(WorkerNameForm.full_name)
async def finish_apply(message: Message, state: FSMContext, session: AsyncSession, bot):
    full_name = " ".join(message.text.strip().split()) if message.text else ""
    if len(full_name.split()) < 2 or len(full_name) > 255:
        await message.answer("Введите, пожалуйста, имя и фамилию, например: Иван Иванов.")
        return

    data = await state.get_data()
    jid = int(data["job_id"])
    user = await upsert_user(session, message.from_user)
    await session.commit()

    try:
        app, status, job = await apply_to_job(session, jid, user, full_name)
    except Exception:
        await session.rollback()
        await message.answer("Не удалось оформить запись. Попробуйте ещё раз.")
        await state.clear()
        return

    if status == "already":
        await message.answer("⚠️ Вы уже записаны на эту работу.")
        await state.clear()
        return
    if status in {"closed", "full", "missing"}:
        await message.answer("⚠️ Набор на эту работу уже закрыт или свободных мест нет.")
        await state.clear()
        return

    job = await get_job(session, jid, with_applications=True)
    filled = await application_count(session, jid) if job else None
    start = job.start_at.astimezone(TZ) if job else None

    await message.answer(
        "✅ Вы записаны на работу!\n\n" + job_text(job, filled),
        reply_markup=cancel_application(jid),
    )

    settings = get_settings()
    if status == "filled":
        for admin_id in settings.admin_id_set:
            try:
                await bot.send_message(
                    admin_id,
                    f"✅ <b>Работники найдены!</b>\n\n"
                    f"Работа: {job.title}\n"
                    f"👥 Требовалось: {job.required_workers}\n"
                    f"👤 Набрано: {job.required_workers}\n"
                    f"📅 {start:%d.%m.%Y %H:%M}\n"
                    f"📍 {job.address}",
                )
            except Exception:
                pass
        try:
            await message.answer("✅ Работники набраны, ваша запись подтверждена.")
        except Exception:
            pass
    await state.clear()


@router.callback_query(F.data.startswith("job:cancel:"))
async def cancel(call: CallbackQuery, session: AsyncSession, bot):
    jid = int(call.data.rsplit(":", 1)[1])
    user = await upsert_user(session, call.from_user)
    await session.commit()

    app, _ = await cancel_app_service(session, jid, user.id)
    if not app:
        await call.answer("Активная запись не найдена", show_alert=True)
        return

    job = await get_job(session, jid, with_applications=True)
    filled = await application_count(session, jid) if job else None
    text = "❌ Вы отменили участие в работе."
    if job:
        text += "\n\n" + job_text(job, filled)
    await call.message.edit_text(text, reply_markup=cancel_application(jid) if job else None)
    await call.answer()
