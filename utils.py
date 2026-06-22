import html
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from config import TZ, TIMES, DAY_MAP
import database as db


def get_next_slot_utc(slot_display: str) -> datetime:
    day_str, h, m = TIMES[slot_display]
    now_tz = datetime.now(TZ)
    days_ahead = DAY_MAP[day_str] - now_tz.weekday()
    if days_ahead <= 0: days_ahead += 7
    next_tz = (now_tz + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
    return next_tz.astimezone(timezone.utc)


def escape_html(text: str) -> str:
    return html.escape(str(text))


async def reminder_loop(bot, tz):
    logging.info("🔔 Reminder loop started")

    # 🛡️ Ждём 5 секунд на старте, чтобы дать время на инициализацию БД
    await asyncio.sleep(5)

    while True:
        try:
            # 🔴 ГЛАВНОЕ ИСПРАВЛЕНИЕ: проверка на None
            if db.pool is None:
                logging.debug("⏳ DB pool not ready, skipping reminder cycle")
                await asyncio.sleep(10)  # Ждём 10 сек перед следующей проверкой
                continue

            check_until = datetime.now(timezone.utc) + timedelta(hours=1)
            bookings = await db.get_upcoming_reminders(check_until)

            for b in bookings:
                try:
                    await bot.send_message(
                        b["user_id"],
                        f"⏰ <b>Напоминание:</b> Консультация через 1 час.",
                        parse_mode="HTML"
                    )
                    await db.mark_reminder_sent(b["id"])
                except Exception as e:
                    logging.error(f"❌ Reminder send error {b['id']}: {e}")

        except Exception as e:
            logging.error(f"❌ Reminder loop error: {e}")

        await asyncio.sleep(60)  # Пауза между циклами
