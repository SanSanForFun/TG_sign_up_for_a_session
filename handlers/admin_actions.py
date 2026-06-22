from aiogram import Router, F
from aiogram.types import CallbackQuery
import database as db
from gcal_service import GoogleCalendarService
from config import TZ
from datetime import timedelta
from logging import error
from utils import escape_html
from config import SERVICES, BOT_TOKEN
from aiogram import Bot
from bot_instance import bot

router = Router()
# bot = Bot(token=BOT_TOKEN)
gcal = None  # Injected in main


@router.callback_query(F.data.startswith("confirm:") | F.data.startswith("reject:"))
async def admin_decision(call: CallbackQuery):
    await call.answer()
    action, _, bid = call.data.partition(":")
    booking = await db.get_booking(int(bid))
    if not booking:
        await call.message.edit_text("⚠️ Заявка не найдена.")
        return

    is_confirmed = action == "confirm"
    await db.update_status(booking["id"], "confirmed" if is_confirmed else "rejected")

    gcal_event_id, meet_link = None, None
    if is_confirmed and gcal and gcal.enabled:
        start_tz = booking["booking_datetime"].astimezone(TZ)
        end_tz = start_tz + timedelta(hours=1)
        desc = f"Услуга: {SERVICES.get(booking['service'], booking['service'])}\nTelegram: @{booking['username'] or 'N/A'}"
        try:
            gcal_event_id, meet_link = await gcal.create_event(
                f"Консультация: {booking['name']}", start_tz, end_tz, desc
            )
            if gcal_event_id:
                await db.update_gcal_id(booking["id"], gcal_event_id)
        except Exception as e:
            error(f"❌ Ошибка создания события в GCal: {e}")

    status_txt = "✅ подтверждена" if is_confirmed else "❌ отклонена"
    await call.message.edit_text(
        call.message.text.replace("⏳ Ожидает", status_txt), parse_mode="HTML", reply_markup=None
    )

    client_msg = f"Ваша запись #{booking['id']} {status_txt} психологом."
    if is_confirmed and meet_link:
        client_msg += f"\n🎥 Ссылка на видеовстречу: {meet_link}"
    elif is_confirmed and booking["service"] == "online":
        client_msg += "\n🔗 Ссылка на встречу будет отправлена за 15 минут до начала."
    await bot.send_message(booking["user_id"], client_msg)
