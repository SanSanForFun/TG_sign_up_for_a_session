from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from config import SERVICES, TIMES
import database as db
from utils import get_next_slot_utc, escape_html
from config import BOT_TOKEN, ADMIN_CHAT_ID, TZ
from aiogram import Bot
from aiogram.filters import Command
from gcal_service import GoogleCalendarService
from datetime import timedelta
from bot_instance import bot

router = Router()
# bot = Bot(token=BOT_TOKEN)
gcal = None  # Инициализируется в main.py


class BookingStates(StatesGroup):
    choosing_service = State()
    choosing_time = State()
    entering_name = State()


@router.callback_query(BookingStates.choosing_service, F.data.startswith("service_"))
async def process_service(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(service=call.data.split("_", 1)[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=slot, callback_data=f"time_{slot}")] for slot in TIMES.keys()
    ])
    await call.message.edit_text("🕒 Выберите удобное время:", reply_markup=kb)
    await state.set_state(BookingStates.choosing_time)


@router.callback_query(BookingStates.choosing_time, F.data.startswith("time_"))
async def process_time(call: CallbackQuery, state: FSMContext):
    await call.answer()
    slot = call.data.split("_", 1)[1]
    if await db.is_slot_taken(slot):
        await call.message.edit_text("⛔️ Этот слот уже занят. Выберите другое время.",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                         [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_time")]
                                     ]))
        return
    await state.update_data(time=slot)
    await call.message.edit_text("✍️ Введите ваше имя:")
    await state.set_state(BookingStates.entering_name)


@router.callback_query(F.data == "back_to_time")
async def back_to_time(call: CallbackQuery, state: FSMContext):
    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=slot, callback_data=f"time_{slot}")] for slot in TIMES.keys()
    ])
    await call.message.edit_text("🕒 Выберите удобное время:", reply_markup=kb)
    await state.set_state(BookingStates.choosing_time)


@router.message(BookingStates.entering_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Имя должно быть минимум 2 символа:")
        return

    await state.update_data(name=name)
    data = await state.get_data()
    booking_dt = get_next_slot_utc(data["time"])
    booking_id = await db.create_booking(
        message.from_user.id, message.from_user.username or "", name, data["service"], data["time"], booking_dt
    )

    await message.answer("✅ Заявка отправлена! Ожидайте подтверждения.")
    await state.clear()

    notify_text = (
        f"🔔 <b>Новая заявка #{booking_id}</b>\n"
        f"👤 {escape_html(name)} | @{message.from_user.username or '—'}\n"
        f"📋 {escape_html(SERVICES.get(data['service'], ''))} | {data['time']}\n"
        f"📅 {booking_dt.astimezone(TZ).strftime('%d.%m %H:%M')} ({TZ.key})\n"
        f"Статус: ⏳ Ожидает"
    )
    kb_admin = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{booking_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{booking_id}")]
    ])
    try:
        await bot.send_message(ADMIN_CHAT_ID, notify_text, parse_mode="HTML", reply_markup=kb_admin)
    except Exception as e:
        from logging import error
        error(f"❌ Не удалось отправить уведомление админу: {e}")
