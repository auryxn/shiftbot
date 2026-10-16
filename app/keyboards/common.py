from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def worker_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Найти работу", callback_data="worker:jobs")],
            [InlineKeyboardButton(text="📋 Мои работы", callback_data="worker:myjobs")],
            [InlineKeyboardButton(text="👤 Мой профиль", callback_data="worker:profile")],
            [
                InlineKeyboardButton(text="🌐 Язык", callback_data="worker:language"),
                InlineKeyboardButton(text="ℹ️ Помощь", callback_data="worker:help"),
            ],
        ]
    )


def back_menu(target: str = "worker:menu"):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=target)]]
    )
