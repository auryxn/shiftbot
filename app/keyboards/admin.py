from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать работу", callback_data="admin:create")],
            [InlineKeyboardButton(text="📋 Активные работы", callback_data="admin:active")],
            [InlineKeyboardButton(text="👥 Набранные работы", callback_data="admin:filled")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="📜 История работ", callback_data="admin:history")],
        ]
    )


def job_actions(job_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Работники", callback_data=f"admin:workers:{job_id}")],
            [
                InlineKeyboardButton(text="✏️ Изменить", callback_data=f"admin:edit:{job_id}"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data=f"admin:close:{job_id}"),
            ],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:delete:{job_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:active")],
        ]
    )
