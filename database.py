import aiosqlite

DB_NAME = "bot_database.db"

async def init_db():
    """Baza va jadvallarni asinxron yaratish."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def add_user(user_id: int, full_name: str, username: str = None):
    """Foydalanuvchini bazaga qo'shish."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, full_name, username)
            VALUES (?, ?, ?)
        """, (user_id, full_name, username))
        await db.commit()

async def get_total_users() -> int:
    """Jami foydalanuvchilar sonini olish (admin.py uchun)."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_all_user_ids() -> list[int]:
    """Reklama yuborish uchun barcha user_id larni olish (admin.py uchun)."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
