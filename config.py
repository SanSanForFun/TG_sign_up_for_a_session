import os
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
DATABASE_URL = os.getenv("DATABASE_URL")
TZ = ZoneInfo(os.getenv("TZ", "Europe/Moscow"))

# Google Calendar
GCAL_ENABLED = os.getenv("GCAL_ENABLED", "false").lower() == "true"
GCAL_CREDS_PATH = os.getenv("GCAL_CREDS_PATH", "service_account.json")
GCAL_CALENDAR_ID = os.getenv("GCAL_CALENDAR_ID")

if not all([BOT_TOKEN, ADMIN_CHAT_ID, DATABASE_URL]):
    raise ValueError("❌ Проверьте .env: BOT_TOKEN, ADMIN_CHAT_ID, DATABASE_URL обязательны")

# 🕒 ВРЕМЯ И РАСПИСАНИЕ
DAY_MAP = {"Пн": 0, "Вт": 1, "Ср": 2, "Чт": 3, "Пт": 4, "Сб": 5, "Вс": 6}
# 🕒 РАСПИСАНИЕ: ключ = отображаемое название, значение = данные для расчёта
TIMES = {
    "Пн 10:00": ("Пн", 10, 0),
    "Пн 11:00": ("Пн", 11, 0),
    "Пн 12:00": ("Пн", 12, 0),
    "Вт 10:00": ("Вт", 10, 0),
    "Вт 11:00": ("Вт", 11, 0),
    "Вт 12:00": ("Вт", 12, 0)
}

# Отдельный словарь для парсинга (можно использовать TIMES.keys() для отображения)
TIME_DATA = TIMES  # алиас для читаемости в логике
SERVICES = {"online": "💻 Online", "individual": "👤 Индивидуальная", "group": "👥 Групповая"}
