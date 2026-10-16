from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import (
    Application,
    ApplicationStatus,
    Job,
    JobStatus,
    Role,
    User,
)
from app.database.repositories import (
    all_jobs,
    application_count,
    get_job,
    job_applications,
    upsert_user,
)
from app.keyboards.admin import admin_menu, job_actions
from app.keyboards.job import work_button
from app.services.formatting import TZ, job_text, money
from app.services.notifications import broadcast_workers
from app.states.forms import JobForm

router = Router()


def is_admin(uid) -> bool:
    return uid in get_settings().admin_id_set


def parse_date_time(date_s, time_s):
    return (
        datetime.strptime(f"{date_s} {time_s}", "%d.%m.%Y %H:%M")
        .replace(tzinfo=TZ)
        .astimezone(timezone.utc)
    )


@router.message(F.text == "/admin")
async def admin(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    await upsert_user(session, message.from_user, Role.ADMIN)
    await session.commit()
    await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:menu")
async def admin_menu_cb(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.edit_text("⚙️ <b>Админ-панель</b>", reply_markup=admin_menu())
    await call.answer()


# ---------------------------------------------------------------- create flow

@router.callback_query(F.data == "admin:create")
async def create_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await state.set_state(JobForm.title)
    await call.message.answer("Введите название работы:")
    await call.answer()


PROMPTS = {
    JobForm.description: "Введите описание работы или '-' если без описания:",
    JobForm.hourly_rate: "Сколько платят в час?",
    JobForm.hours: "Сколько часов работать?",
    JobForm.date: "На какую дату? Формат ДД.ММ.ГГГГ",
    JobForm.arrival_time: "Во сколько нужно приехать? Формат ЧЧ:ММ",
    JobForm.address: "Введите адрес работы:",
    JobForm.required_workers: "Сколько работников нужно?",
}


@router.message(JobForm.title)
async def title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(JobForm.description)
    await message.answer(PROMPTS[JobForm.description])


@router.message(JobForm.description)
async def desc(message: Message, state: FSMContext):
    await state.update_data(description=None if message.text.strip() == "-" else message.text.strip())
    await state.set_state(JobForm.hourly_rate)
    await message.answer(PROMPTS[JobForm.hourly_rate])


@router.message(JobForm.hourly_rate)
async def rate(message: Message, state: FSMContext):
    try:
        v = float(message.text.replace(",", "."))
        assert v > 0
    except Exception:
        await message.answer("Введите положительное число, например 10")
        return
    await state.update_data(hourly_rate=v)
    await state.set_state(JobForm.hours)
    await message.answer(PROMPTS[JobForm.hours])


@router.message(JobForm.hours)
async def hours(message: Message, state: FSMContext):
    try:
        v = float(message.text.replace(",", "."))
        assert v > 0
    except Exception:
        await message.answer("Введите количество часов, например 8")
        return
    await state.update_data(hours=v)
    await state.set_state(JobForm.date)
    await message.answer(PROMPTS[JobForm.date])


@router.message(JobForm.date)
async def date_(message: Message, state: FSMContext):
    try:
        datetime.strptime(message.text.strip(), "%d.%m.%Y")
    except Exception:
        await message.answer("Формат: 20.09.2026")
        return
    await state.update_data(date=message.text.strip())
    await state.set_state(JobForm.arrival_time)
    await message.answer(PROMPTS[JobForm.arrival_time])


@router.message(JobForm.arrival_time)
async def time_(message: Message, state: FSMContext):
    try:
        datetime.strptime(message.text.strip(), "%H:%M")
    except Exception:
        await message.answer("Формат: 08:00")
        return
    await state.update_data(arrival_time=message.text.strip())
    await state.set_state(JobForm.address)
    await message.answer(PROMPTS[JobForm.address])


@router.message(JobForm.address)
async def address(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    await state.set_state(JobForm.required_workers)
    await message.answer(PROMPTS[JobForm.required_workers])


def preview_text(data: dict) -> str:
    return (
        f"📦 <b>{data['title']}</b>\n\n"
        f"{data.get('description') or ''}\n\n"
        f"💰 {money(data['hourly_rate'])} €/час\n"
        f"⏱ {money(data['hours'])} часов\n"
        f"💵 За смену: {money(float(data['hourly_rate']) * float(data['hours']))} €\n\n"
        f"📅 {data['date']}\n"
        f"🕐 Приехать к {data['arrival_time']}\n"
        f"📍 {data['address']}\n"
        f"👥 Требуется: {data['required_workers']}\n"
        f"👤 Уже набрано: 0/{data['required_workers']}"
    )


def preview_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Опубликовать", callback_data="admin:publish")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="admin:editdraft")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin:canceldraft")],
        ]
    )


@router.callback_query(JobForm.preview, F.data == "admin:editdraft")
async def edit_draft(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "✏️ Что изменить?\n\nВведите название заново, чтобы пройти шаги с начала.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Начать заново", callback_data="admin:create")],
                [InlineKeyboardButton(text="⬅️ Вернуться к превью", callback_data="admin:preview")],
            ]
        ),
    )
    await call.answer()


@router.callback_query(JobForm.preview, F.data == "admin:preview")
async def back_to_preview(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await call.message.edit_text(preview_text(data), reply_markup=preview_kb())
    await call.answer()


@router.message(JobForm.required_workers)
async def workers_input(message: Message, state: FSMContext):
    try:
        v = int(message.text)
        assert v > 0
    except Exception:
        await message.answer("Введите целое число больше 0.")
        return
    await state.update_data(required_workers=v)
    data = await state.get_data()
    await state.set_state(JobForm.preview)
    await message.answer(preview_text(data), reply_markup=preview_kb())


@router.callback_query(JobForm.preview, F.data == "admin:publish")
async def publish(call: CallbackQuery, state: FSMContext, session: AsyncSession, bot):
    data = await state.get_data()
    try:
        start = parse_date_time(data["date"], data["arrival_time"])
    except Exception:
        await call.answer("Ошибка даты", show_alert=True)
        return
    user = await upsert_user(session, call.from_user, Role.ADMIN)
    job = Job(
        title=data["title"],
        description=data.get("description"),
        hourly_rate=data["hourly_rate"],
        hours=data["hours"],
        start_at=start,
        address=data["address"],
        required_workers=data["required_workers"],
        status=JobStatus.ACTIVE,
        created_by=user.id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    await session.commit()
    await state.clear()
    await call.message.edit_text(
        "✅ Работа опубликована.", reply_markup=admin_menu()
    )
    await call.answer()
    workers = (
        (await session.execute(select(User).where(User.role == Role.WORKER)))
        .scalars()
        .all()
    )
    await broadcast_workers(
        session, bot, "🔥 <b>Новая подработка!</b>\n\n" + job_text(job, 0),
        reply_markup=work_button(job.id),
    )


@router.callback_query(F.data == "admin:canceldraft")
async def cancel_draft(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Черновик отменён.", reply_markup=admin_menu())
    await call.answer()


# ------------------------------------------------------------- active / filled

@router.callback_query(F.data == "admin:active")
async def active(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jobs = await all_jobs(session, status=JobStatus.ACTIVE)
    if not jobs:
        await call.message.edit_text("📋 Активных работ нет.", reply_markup=admin_menu())
        await call.answer()
        return

    lines = ["🟢 <b>Активные работы</b>"]
    buttons = []
    for j in jobs:
        start = j.start_at.astimezone(TZ)
        count = len([a for a in j.applications if a.status == ApplicationStatus.ACTIVE])
        lines.append(
            f"\n#{j.id} <b>{j.title}</b> — {start:%d.%m %H:%M}\n"
            f"   👥 {count}/{j.required_workers} · 📍 {j.address}"
        )
        buttons.append(
            [InlineKeyboardButton(text=f"⚙️ #{j.id} {j.title}", callback_data=f"admin:job:{j.id}")]
        )
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")])
    await call.message.edit_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:job:"))
async def job_card(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jid = int(call.data.rsplit(":", 1)[1])
    job = await get_job(session, jid, with_applications=True)
    if not job:
        await call.answer("Работа не найдена", show_alert=True)
        return
    count = await application_count(session, jid)
    statuses = {
        JobStatus.ACTIVE: "🟢 Набор открыт",
        JobStatus.FILLED: "🟡 Набрано",
        JobStatus.CLOSED: "🔴 Закрыто",
        JobStatus.COMPLETED: "✅ Завершено",
        JobStatus.DRAFT: "📝 Черновик",
    }
    await call.message.edit_text(
        job_text(job, count) + f"\n\n{statuses.get(job.status, job.status.value)}",
        reply_markup=job_actions(job.id),
    )
    await call.answer()


@router.callback_query(F.data == "admin:filled")
async def filled(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jobs = await all_jobs(session, status=JobStatus.FILLED)
    if not jobs:
        await call.message.edit_text("👥 Набранных работ нет.", reply_markup=admin_menu())
        await call.answer()
        return
    lines = ["👥 <b>Набранные работы</b>"]
    buttons = []
    for j in jobs:
        count = len([a for a in j.applications if a.status == ApplicationStatus.ACTIVE])
        start = j.start_at.astimezone(TZ)
        lines.append(
            f"\n#{j.id} <b>{j.title}</b> — {count}/{j.required_workers} · 📅 {start:%d.%m %H:%M}"
        )
        buttons.append(
            [InlineKeyboardButton(text=f"👥 #{j.id} {j.title}", callback_data=f"admin:workers:{j.id}")]
        )
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")])
    await call.message.edit_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()


# ------------------------------------------------------------------- job admin

@router.callback_query(F.data.startswith("admin:close:"))
async def close(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jid = int(call.data.rsplit(":", 1)[1])
    job = await get_job(session, jid)
    if job:
        job.status = JobStatus.CLOSED
        await session.commit()
        await call.message.edit_text("❌ Набор закрыт.", reply_markup=admin_menu())
    else:
        await call.answer("Работа не найдена", show_alert=True)
    await call.answer()


@router.callback_query(F.data.startswith("admin:delete:"))
async def delete_job(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jid = int(call.data.rsplit(":", 1)[1])
    await session.execute(delete(Application).where(Application.job_id == jid))
    await session.execute(delete(Job).where(Job.id == jid))
    await session.commit()
    await call.message.edit_text("🗑 Работа удалена.", reply_markup=admin_menu())
    await call.answer()


@router.callback_query(F.data.startswith("admin:workers:"))
async def workers(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jid = int(call.data.rsplit(":", 1)[1])
    job = await get_job(session, jid)
    rows = await job_applications(session, jid, active_only=True)
    if rows:
        body = "\n".join(
            f"{i}. {a.full_name} — @{u.username or 'нет'} — ID {u.telegram_id}"
            for i, (a, u) in enumerate(rows, 1)
        )
        text = f"👥 <b>Работники</b>\n\n{body}"
    else:
        text = "Работников пока нет."
    buttons = []
    if job:
        buttons.append([InlineKeyboardButton(text="⬅️ К работе", callback_data=f"admin:job:{job.id}")])
    buttons.append([InlineKeyboardButton(text="⚙️ В меню", callback_data="admin:menu")])
    await call.message.edit_text(
        text + (f"\n\n👥 {len(rows)}/{job.required_workers}" if job else ""),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await call.answer()


@router.callback_query(F.data == "admin:stats")
async def stats(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jobs = int((await session.execute(select(func.count(Job.id)))).scalar_one())
    active_apps = int(
        (
            await session.execute(
                select(func.count(Application.id)).where(
                    Application.status == ApplicationStatus.ACTIVE
                )
            )
        ).scalar_one()
    )
    users = int((await session.execute(select(func.count(User.id)))).scalar_one())
    filled = int(
        (
            await session.execute(
                select(func.count(Job.id)).where(Job.status == JobStatus.FILLED)
            )
        ).scalar_one()
    )
    await call.message.edit_text(
        f"📊 <b>Статистика</b>\n\n"
        f"Объявлений: {jobs}\n"
        f"Набрано: {filled}\n"
        f"Активных записей: {active_apps}\n"
        f"Пользователей: {users}",
        reply_markup=admin_menu(),
    )
    await call.answer()


@router.callback_query(F.data == "admin:history")
async def history(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jobs = (await session.execute(
        select(Job).order_by(Job.created_at.desc()).limit(20)
    )).scalars().all()
    if not jobs:
        await call.message.edit_text("📜 История пуста.", reply_markup=admin_menu())
        await call.answer()
        return
    lines = ["📜 <b>История работ</b>"]
    for j in jobs:
        lines.append(
            f"#{j.id} {j.title} — {j.status.value} — {j.created_at.astimezone(TZ):%d.%m.%Y}"
        )
    await call.message.edit_text("\n".join(lines), reply_markup=admin_menu())
    await call.answer()


@router.callback_query(F.data.startswith("admin:edit:"))
async def edit_job(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jid = int(call.data.rsplit(":", 1)[1])
    job = await get_job(session, jid, with_applications=True)
    if not job:
        await call.answer("Работа не найдена", show_alert=True)
        return
    count = await application_count(session, jid)
    await call.message.edit_text(
        job_text(job, count)
        + "\n\n✏️ <b>Редактирование</b>\n\n"
        "Быстрые действия:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="👥 +1 место", callback_data=f"admin:inc:{jid}"),
                    InlineKeyboardButton(text="👥 -1 место", callback_data=f"admin:dec:{jid}"),
                ],
                [
                    InlineKeyboardButton(text="🟢 Открыть набор", callback_data=f"admin:open:{jid}"),
                    InlineKeyboardButton(text="✅ Завершить", callback_data=f"admin:finish:{jid}"),
                ],
                [InlineKeyboardButton(text="⬅️ К работе", callback_data=f"admin:job:{jid}")],
            ]
        ),
    )
    await call.answer()


async def _bump_places(call: CallbackQuery, session: AsyncSession, delta: int):
    jid = int(call.data.rsplit(":", 1)[1])
    job = await get_job(session, jid, with_applications=True)
    if not job:
        await call.answer("Работа не найдена", show_alert=True)
        return
    count = await application_count(session, jid)
    new_value = max(job.required_workers + delta, 1)
    if new_value < count:
        await call.answer(
            f"Нельзя: уже записано {count} человек.", show_alert=True
        )
        return
    job.required_workers = new_value
    if job.status == JobStatus.FILLED and new_value > count:
        job.status = JobStatus.ACTIVE
    await session.commit()
    await call.answer(f"Теперь нужно: {new_value}")


@router.callback_query(F.data.startswith("admin:inc:"))
async def inc_places(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await _bump_places(call, session, 1)


@router.callback_query(F.data.startswith("admin:dec:"))
async def dec_places(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await _bump_places(call, session, -1)


@router.callback_query(F.data.startswith("admin:open:"))
async def reopen(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jid = int(call.data.rsplit(":", 1)[1])
    job = await get_job(session, jid)
    if not job:
        await call.answer("Работа не найдена", show_alert=True)
        return
    job.status = JobStatus.ACTIVE
    await session.commit()
    await call.answer("🟢 Набор открыт")


@router.callback_query(F.data.startswith("admin:finish:"))
async def finish_job(call: CallbackQuery, session: AsyncSession):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    jid = int(call.data.rsplit(":", 1)[1])
    job = await get_job(session, jid)
    if not job:
        await call.answer("Работа не найдена", show_alert=True)
        return
    job.status = JobStatus.COMPLETED
    apps = (
        (
            await session.execute(
                select(Application).where(
                    Application.job_id == jid,
                    Application.status == ApplicationStatus.ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )
    for a in apps:
        a.status = ApplicationStatus.COMPLETED
    await session.commit()
    await call.answer("✅ Работа завершена")
