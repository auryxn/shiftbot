from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Application, ApplicationStatus, Job
from app.database.repositories import active_jobs, application_count, get_job, upsert_user
from app.keyboards.common import back_menu, worker_menu
from app.keyboards.job import cancel_application, work_button
from app.services.formatting import TZ, job_text, money

router = Router()


@router.callback_query(F.data == "worker:menu")
async def menu(call: CallbackQuery):
    if not call.message:
        await call.answer()
        return
    await call.message.edit_text("👋 Главное меню", reply_markup=worker_menu())
    await call.answer()


@router.callback_query(F.data == "worker:jobs")
async def jobs(call: CallbackQuery, session: AsyncSession):
    jobs = await active_jobs(session)
    if not jobs:
        await call.message.edit_text(
            "🔎 Сейчас активных подработок нет.", reply_markup=back_menu()
        )
        await call.answer()
        return

    lines = ["🔥 <b>Доступные подработки</b>"]
    buttons = []
    for j in jobs:
        count = len([a for a in j.applications if a.status == ApplicationStatus.ACTIVE])
        start = j.start_at.astimezone(TZ)
        lines.append(
            f"\n📦 <b>{j.title}</b>\n"
            f"💰 {money(j.hourly_rate)} €/час\n"
            f"📅 {start:%d.%m %H:%M}\n"
            f"📍 {j.address}\n"
            f"👥 Свободно: {max(j.required_workers - count, 0)}"
        )
        buttons.append(
            [
                __import__("aiogram").types.InlineKeyboardButton(
                    text=f"Подробнее: {j.title}", callback_data=f"job:view:{j.id}"
                )
            ]
        )
    buttons.append(
        [
            __import__("aiogram").types.InlineKeyboardButton(
                text="⬅️ Назад", callback_data="worker:menu"
            )
        ]
    )
    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=__import__("aiogram").types.InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await call.answer()


@router.callback_query(F.data.startswith("job:view:"))
async def job_view(call: CallbackQuery, session: AsyncSession):
    jid = int(call.data.rsplit(":", 1)[1])
    job = await get_job(session, jid, with_applications=True)
    if not job:
        await call.answer("Работа не найдена", show_alert=True)
        return

    user = await upsert_user(session, call.from_user)
    await session.commit()

    count = await application_count(session, job.id)
    mine = (
        await session.execute(
            __import__("sqlalchemy").select(Application).where(
                Application.job_id == job.id,
                Application.user_id == user.id,
                Application.status == ApplicationStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()

    markup = cancel_application(job.id) if mine else work_button(job.id)
    await call.message.edit_text(job_text(job, count), reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "worker:myjobs")
async def myjobs(call: CallbackQuery, session: AsyncSession):
    user = await upsert_user(session, call.from_user)
    await session.commit()
    apps = (
        (
            await session.execute(
                __import__("sqlalchemy")
                .select(Application)
                .where(
                    Application.user_id == user.id,
                    Application.status == ApplicationStatus.ACTIVE,
                )
                .order_by(Application.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if not apps:
        await call.message.edit_text(
            "📋 У вас пока нет активных записей.", reply_markup=back_menu()
        )
        await call.answer()
        return

    blocks = []
    buttons = []
    for a in apps:
        j = await get_job(session, a.job_id, with_applications=True)
        if not j:
            continue
        count = await application_count(session, j.id)
        blocks.append(job_text(j, count))
        buttons.append(
            [
                __import__("aiogram").types.InlineKeyboardButton(
                    text=f"❌ Отменить: {j.title}", callback_data=f"job:cancel:{j.id}"
                )
            ]
        )
    buttons.append(
        [
            __import__("aiogram").types.InlineKeyboardButton(
                text="⬅️ Назад", callback_data="worker:menu"
            )
        ]
    )
    await call.message.edit_text(
        "📋 <b>Мои работы</b>\n\n" + "\n\n".join(blocks),
        reply_markup=__import__("aiogram").types.InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await call.answer()


@router.callback_query(F.data == "worker:profile")
async def profile(call: CallbackQuery, session: AsyncSession):
    user = await upsert_user(session, call.from_user)
    await session.commit()
    completed = int(
        (
            await session.execute(
                __import__("sqlalchemy").select(
                    __import__("sqlalchemy").func.count(Application.id)
                ).where(
                    Application.user_id == user.id,
                    Application.status == ApplicationStatus.COMPLETED,
                )
            )
        ).scalar_one()
    )
    active = int(
        (
            await session.execute(
                __import__("sqlalchemy").select(
                    __import__("sqlalchemy").func.count(Application.id)
                ).where(
                    Application.user_id == user.id,
                    Application.status == ApplicationStatus.ACTIVE,
                )
            )
        ).scalar_one()
    )
    await call.message.edit_text(
        f"👤 <b>Мой профиль</b>\n\n"
        f"Имя: {((user.first_name or '') + ' ' + (user.last_name or '')).strip() or 'не указано'}\n"
        f"Telegram: @{user.username or 'нет'}\n\n"
        f"Активных работ: {active}\n"
        f"Завершённых работ: {completed}\n"
        f"Зарегистрирован: {user.created_at.astimezone(TZ):%d.%m.%Y}",
        reply_markup=back_menu(),
    )
    await call.answer()


@router.callback_query(F.data == "worker:help")
async def help_(call: CallbackQuery):
    await call.message.edit_text(
        "ℹ️ Выберите подработку, нажмите «Работать» и укажите имя и фамилию. "
        "При необходимости участие можно отменить: в карточке работы или в «Мои работы».",
        reply_markup=back_menu(),
    )
    await call.answer()


@router.callback_query(F.data == "worker:language")
async def language(call: CallbackQuery):
    await call.message.edit_text(
        "🌐 Язык: русский / English / lietuvių.\n\n"
        "В MVP интерфейс подготовлен к локализации; сейчас основной язык — русский. "
        "Выбор языка появится в следующем обновлении.",
        reply_markup=back_menu(),
    )
    await call.answer()
