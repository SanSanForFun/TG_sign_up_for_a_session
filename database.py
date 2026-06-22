import logging
from typing import Optional
import asyncpg

pool: Optional[asyncpg.Pool] = None


async def init_db(dsn: str):
    global pool
    logging.info(f"🔌 Подключение к БД: {dsn[:30]}...")  # Скрываем пароль
    pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)

    async with pool.acquire() as conn:
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
                gcal_event_id TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        logging.info("🗃️ Таблица bookings проверена/создана")


async def close_db():
    global pool
    if pool:
        await pool.close()
        logging.info("🔌 PostgreSQL pool closed")


# --- CRUD ---
async def is_slot_taken(slot_code: str) -> bool:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT 1 FROM bookings WHERE slot_code = $1 AND status IN ('pending', 'confirmed') LIMIT 1", slot_code
        ) is not None


async def create_booking(user_id, username, name, service, slot_code, booking_dt) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO bookings (user_id, username, name, service, slot_code, booking_datetime) VALUES ($1,$2,$3,$4,$5,$6) RETURNING id",
            user_id, username, name, service, slot_code, booking_dt
        )


async def get_booking(booking_id: int) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM bookings WHERE id = $1", booking_id)
        return dict(row) if row else None


async def update_status(booking_id: int, status: str):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET status = $1 WHERE id = $2", status, booking_id)


async def update_gcal_id(booking_id: int, event_id: Optional[str]):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET gcal_event_id = $1 WHERE id = $2", event_id, booking_id)


async def get_user_active_booking(user_id: int) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bookings WHERE user_id = $1 AND status IN ('pending','confirmed') ORDER BY created_at DESC LIMIT 1",
            user_id
        )
        return dict(row) if row else None


async def get_upcoming_reminders(check_until) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM bookings WHERE status='confirmed' AND reminder_sent=FALSE AND booking_datetime <= $1",
            check_until
        )
        return [dict(r) for r in rows]


async def mark_reminder_sent(booking_id: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET reminder_sent = TRUE WHERE id = $1", booking_id)
