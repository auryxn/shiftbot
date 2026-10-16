from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def work_button(job_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Работать", callback_data=f"job:apply:{job_id}")]]
    )


def cancel_application(job_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отменить участие", callback_data=f"job:cancel:{job_id}"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="worker:myjobs")],
        ]
    )
