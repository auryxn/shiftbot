from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import Role
from app.database.repositories import upsert_user
from app.keyboards.admin import admin_menu
from app.keyboards.common import worker_menu

router = Router()


@router.message(CommandStart())
async def start(message: Message, session: AsyncSession):
    settings = get_settings()
    role = Role.ADMIN if message.from_user.id in settings.admin_id_set else Role.WORKER
    await upsert_user(session, message.from_user, role)
    await session.commit()
    if role == Role.ADMIN:
        await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_menu())
    else:
        await message.answer(
            "👋 Добро пожаловать!\n\n"
            "Здесь вы можете находить подработки и записываться на свободные смены.",
            reply_markup=worker_menu(),
        )
