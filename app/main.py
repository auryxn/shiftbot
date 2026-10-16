import asyncio, logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from app.config import get_settings
from app.handlers import start, worker, applications, admin
from app.middlewares.db import DbSessionMiddleware
from app.database.session import SessionLocal
from app.services.notifications import reminder_loop

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings=get_settings()
    bot=Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp=Dispatcher()
    db=DbSessionMiddleware()
    for router in [start.router,admin.router,applications.router,worker.router]:
        router.message.middleware(db); router.callback_query.middleware(db)
        dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=False)
    reminder_task = asyncio.create_task(reminder_loop(bot, SessionLocal))
    try:
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()
        await bot.session.close()

if __name__=="__main__": asyncio.run(main())
