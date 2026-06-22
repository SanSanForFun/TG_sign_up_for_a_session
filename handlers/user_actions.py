from aiogram import Router, F
from aiogram.types import CallbackQuery
import database as db
from gcal_service import GoogleCalendarService
from logging import error
from utils import escape_html
from config import SERVICES, BOT_TOKEN, TZ, ADMIN_CHAT_ID
from aiogram import Bot
from bot_instance import bot

router = Router()
# bot = Bot(token=BOT_TOKEN)
gcal = None  # Injected


@router.callback_query(F.data == "my_booking")
async def my_booking(call: CallbackQuery):
    await call.answer()
    booking = await db.get_user_active_booking(call.from_user.id)
    if not booking:
        await call.message.answer("📭 У вас нет активных записей.")
        return
    status_map = {"pending": "⏳ Ожидает", "confirmed": "✅ Подтверждена"}
    dt = booking["booking_datetime"].astimezone(TZ).strftime("%d.%m %H:%M")
    kb = __import__('aiogram.types', fromlist=['InlineKeyboardButton', 'InlineKeyboardMarkup'])
    markup = kb.InlineKeyboardMarkup(inline_keyboard=[
        [kb.InlineKeyboardButton(text="🗑 Отменить", callback_data=f"cancel:{booking['id']}")]
    ])
    text = f"📋 <b>Запись #{booking['id']}</b>\n📋 {escape_html(SERVICES.get(booking['service'], ''))}\n🕒 {escape_html(booking['slot_code'])} ({dt})\n📌 {status_map.get(booking['status'], booking['status'])}"
    await call.message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_booking(call: CallbackQuery):
    await call.answer()
    _, _, bid = call.data.partition(":")
    booking = await db.get_booking(int(bid))
    if not booking or booking["user_id"] != call.from_user.id or booking["status"] in ("canceled", "rejected"):
        await call.message.edit_text("⚠️ Невозможно отменить эту запись.")
        return

    if booking.get("gcal_event_id") and gcal and gcal.enabled:
        try:
            await gcal.delete_event(booking["gcal_event_id"])
        except Exception as e:
            error(f"❌ Ошибка удаления из GCal: {e}")

    await db.update_status(booking["id"], "canceled")
    await call.message.edit_text("🗑 Запись успешно отменена.")
    await bot.send_message(ADMIN_CHAT_ID, f"🗑 Клиент отменил запись #{booking['id']}\n👤 {escape_html(booking['name'])}")
