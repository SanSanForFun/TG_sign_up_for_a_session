import os
import asyncio
import logging
import html
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

import asyncpg
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# 🔑 ЗАГРУЗКА КОНФИГА
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
DATABASE_URL = os.getenv("DATABASE_URL")
TZ = ZoneInfo(os.getenv("TZ", "Europe/Moscow"))

if not BOT_TOKEN or not ADMIN_CHAT_ID or not DATABASE_URL:
    raise RuntimeError("❌ Проверьте .env: BOT_TOKEN, ADMIN_CHAT_ID, DATABASE_URL обязательны")
ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)

# 🤖 AIОGRAM INIT
dp = Dispatcher(storage=MemoryStorage())
bot = Bot(token=BOT_TOKEN)
db_pool: Optional[asyncpg.Pool] = None


# 🗃️ POSTGRESQL
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=2, max_size=10)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username TEXT,
                name TEXT NOT NULL,
                service TEXT NOT NULL,
                slot_code TEXT NOT NULL,
                booking_datetime TIMESTAMPTZ NOT NULL,
                status TEXT DEFAULT 'pending',
                reminder_sent BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_user_status ON bookings(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_slot_status ON bookings(slot_code, status);
        """)
    logging.info("🗃️ PostgreSQL initialized")


async def close_db():
    if db_pool:
        await db_pool.close()
        logging.info("🔌 PostgreSQL pool closed")


async def db_is_slot_taken(slot_code: str) -> bool:
    async with db_pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT 1 FROM bookings WHERE slot_code = $1 AND status IN ('pending', 'confirmed') LIMIT 1", slot_code
        ) is not None


async def db_create_booking(user_id, username, name, service, slot_code, booking_dt) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO bookings (user_id, username, name, service, slot_code, booking_datetime) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            user_id, username, name, service, slot_code, booking_dt
        )


async def db_get_booking(booking_id: int) -> Optional[dict]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM bookings WHERE id = $1", booking_id)
        return dict(row) if row else None


async def db_update_status(booking_id: int, status: str):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET status = $1 WHERE id = $2", status, booking_id)


async def db_get_user_active_booking(user_id: int) -> Optional[dict]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bookings WHERE user_id = $1 AND status IN ('pending', 'confirmed') ORDER BY created_at DESC LIMIT 1",
            user_id
        )
        return dict(row) if row else None


async def db_get_upcoming_reminders(check_until: datetime) -> list[dict]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM bookings WHERE status = 'confirmed' AND reminder_sent = FALSE AND booking_datetime <= $1",
            check_until
        )
        return [dict(r) for r in rows]


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


def get_next_slot_utc(slot_display: str) -> datetime:
    """Принимает отображаемое название слота, например 'Пн 10:00'"""
    day_str, h, m = TIME_DATA[slot_display]
    now_tz = datetime.now(TZ)
    days_ahead = DAY_MAP[day_str] - now_tz.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_tz = (now_tz + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
    return next_tz.astimezone(timezone.utc)


# 🔄 FSM
class BookingStates(StatesGroup):
    choosing_service = State()
    choosing_time = State()
    entering_name = State()


# 🤖 ХЕНДЛЕРЫ
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="start_booking")],
        [InlineKeyboardButton(text="📋 Моя запись", callback_data="my_booking")]
    ])
    await message.answer("Здравствуйте! 👋\nВыберите действие:", reply_markup=kb)


@dp.callback_query(F.data == "start_booking")
async def start_booking(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"service_{code}")] for code, name in SERVICES.items()
    ])
    await call.message.edit_text("📋 Выберите тип консультации:", reply_markup=kb)
    await state.set_state(BookingStates.choosing_service)


@dp.callback_query(BookingStates.choosing_service, F.data.startswith("service_"))
async def process_service(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(service=call.data.split("_", 1)[1])

    # ✅ Ключ (slot_display) — это и есть текст кнопки
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=slot_display, callback_data=f"time_{slot_display}")]
        for slot_display in TIMES.keys()
    ])
    await call.message.edit_text("🕒 Выберите удобное время:", reply_markup=kb)
    await state.set_state(BookingStates.choosing_time)


@dp.callback_query(BookingStates.choosing_time, F.data.startswith("time_"))
async def process_time(call: CallbackQuery, state: FSMContext):
    await call.answer()
    # Извлекаем отображаемое название из callback_data
    slot_display = call.data.split("_", 1)[1]  # "Пн 10:00"

    if await db_is_slot_taken(slot_display):
        await call.message.edit_text("⛔️ Этот слот уже занят. Выберите другое время.",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                         [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_time")]
                                     ]))
        return

    await state.update_data(time=slot_display)  # сохраняем строку "Пн 10:00"
    await call.message.edit_text("✍️ Введите ваше имя:")
    await state.set_state(BookingStates.entering_name)


@dp.callback_query(F.data == "back_to_time")
async def back_to_time(call: CallbackQuery, state: FSMContext):
    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=slot_display, callback_data=f"time_{slot_display}")]
        for slot_display in TIMES.keys()
    ])
    await call.message.edit_text("🕒 Выберите удобное время:", reply_markup=kb)
    await state.set_state(BookingStates.choosing_time)


@dp.message(BookingStates.entering_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Имя должно быть минимум 2 символа:")
        return

    await state.update_data(name=name)
    data = await state.get_data()
    booking_dt = get_next_slot_utc(data["time"])
    booking_id = await db_create_booking(message.from_user.id, message.from_user.username or "", name, data["service"],
                                         data["time"], booking_dt)

    await message.answer("✅ Заявка отправлена! Ожидайте подтверждения.")
    await state.clear()

    notify_text = (
        f"🔔 <b>Новая заявка #{booking_id}</b>\n"
        f"👤 {html.escape(name)} | @{message.from_user.username or '—'}\n"
        f"📋 {html.escape(SERVICES.get(data['service'], ''))} | {data['time']}\n"
        f"📅 {booking_dt.astimezone(TZ).strftime('%d.%m %H:%M')} ({TZ.key})\n"
        f"Статус: ⏳ Ожидает"
    )
    kb_admin = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{booking_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{booking_id}")]
    ])
    await bot.send_message(ADMIN_CHAT_ID, notify_text, parse_mode="HTML", reply_markup=kb_admin)


@dp.callback_query(F.data.startswith("confirm:") | F.data.startswith("reject:"))
async def admin_decision(call: CallbackQuery):
    await call.answer()
    action, _, bid = call.data.partition(":")
    booking = await db_get_booking(int(bid))
    if not booking:
        await call.message.edit_text("⚠️ Заявка не найдена.")
        return

    new_status = "confirmed" if action == "confirm" else "rejected"
    await db_update_status(booking["id"], new_status)

    status_txt = "✅ подтверждена" if action == "confirm" else "❌ отклонена"
    await call.message.edit_text(call.message.text.replace("⏳ Ожидает", status_txt), parse_mode="HTML",
                                 reply_markup=None)
    await bot.send_message(booking["user_id"], f"Ваша запись #{booking['id']} {status_txt}.")


@dp.callback_query(F.data == "my_booking")
async def my_booking(call: CallbackQuery):
    await call.answer()
    booking = await db_get_user_active_booking(call.from_user.id)
    if not booking:
        await call.message.answer("📭 У вас нет активных записей.")
        return
    status_map = {"pending": "⏳ Ожидает", "confirmed": "✅ Подтверждена"}
    dt = booking["booking_datetime"].astimezone(TZ).strftime("%d.%m %H:%M")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Отменить", callback_data=f"cancel:{booking['id']}")]
    ])
    text = f"📋 <b>Запись #{booking['id']}</b>\n📋 {html.escape(SERVICES.get(booking['service'], ''))}\n🕒 {html.escape(booking['slot_code'])} ({dt})\n📌 {status_map.get(booking['status'], booking['status'])}"
    await call.message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_booking(call: CallbackQuery):
    await call.answer()
    _, _, bid = call.data.partition(":")
    booking = await db_get_booking(int(bid))
    if not booking or booking["user_id"] != call.from_user.id or booking["status"] in ("canceled", "rejected"):
        await call.message.edit_text("⚠️ Невозможно отменить эту запись.")
        return
    await db_update_status(booking["id"], "canceled")
    await call.message.edit_text("🗑 Запись успешно отменена.")
    await bot.send_message(ADMIN_CHAT_ID, f"🗑 Клиент отменил запись #{booking['id']}\n👤 {html.escape(booking['name'])}")


# 🔔 ФОНОВОЕ ЗАДАНИЕ: НАПОМИНАНИЯ
async def reminder_loop():
    logging.info("🔔 Reminder loop started")
    while True:
        try:
            check_until = datetime.now(timezone.utc) + timedelta(hours=1)
            bookings = await db_get_upcoming_reminders(check_until)
            for b in bookings:
                try:
                    await bot.send_message(
                        b["user_id"],
                        f"⏰ <b>Напоминание:</b> Консультация начнётся через 1 час.\n"
                        f"📋 {html.escape(SERVICES.get(b['service'], ''))} в {html.escape(b['slot_code'])}",
                        parse_mode="HTML"
                    )
                    await db_update_status(b["id"], status=bookings["status"])  # keep status, just update reminder flag
                    await db_pool.execute("UPDATE bookings SET reminder_sent = TRUE WHERE id = $1", b["id"])
                    logging.info(f"📩 Reminder sent to {b['user_id']}")
                except Exception as e:
                    logging.error(f"❌ Reminder send error {b['id']}: {e}")
        except Exception as e:
            logging.error(f"❌ Reminder loop error: {e}")
        await asyncio.sleep(60)


# 🚀 ЗАПУСК
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    dp.startup.register(init_db)
    dp.shutdown.register(close_db)

    await asyncio.gather(
        dp.start_polling(bot),
        reminder_loop()
    )


if __name__ == "__main__":
    asyncio.run(main())
