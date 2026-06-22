import sys
import asyncio

if sys.platform == "darwin":  # macOS
    # Используем SelectorEventLoop вместо стандартного на macOS
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
import config
import database as db
from gcal_service import GoogleCalendarService
from utils import reminder_loop
from handlers import start, booking_flow, admin_actions, user_actions

# Инициализация GCal
gcal_service = GoogleCalendarService(
    creds_path=config.GCAL_CREDS_PATH,
    calendar_id=config.GCAL_CALENDAR_ID,
    tz_key=config.TZ.key,
    enabled=config.GCAL_ENABLED
)

# Inject GCal в хендлеры (простой способ для модулей)
for mod in [admin_actions, user_actions, booking_flow]:
    mod.gcal = gcal_service


# В начале main.py, после импортов:
async def on_startup(bot: Bot):
    """Вызывается автоматически при запуске бота"""
    await db.init_db(config.DATABASE_URL)
    logging.info("✅ Бот запущен, БД инициализирована")


async def on_shutdown(bot: Bot):
    """Вызывается автоматически при остановке бота"""
    await db.close_db()
    logging.info("🛑 Бот остановлен, соединения закрыты")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Передаём зависимости в контекст
    dp.workflow_data["bot"] = bot
    dp.workflow_data["gcal"] = gcal_service

    # ✅ Регистрируем хуки правильно (без лямбд!)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Регистрируем роутеры
    dp.include_router(start.router)
    dp.include_router(booking_flow.router)
    dp.include_router(admin_actions.router)
    dp.include_router(user_actions.router)

    # Запуск
    await asyncio.gather(
        dp.start_polling(bot),
        reminder_loop(bot, config.TZ)
    )


if __name__ == "__main__":
    asyncio.run(main())
