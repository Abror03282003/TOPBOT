import aiosqlite

DB_NAME = "bot_database.db"

async def init_db():
    """Baza va jadvallarni yaratish (Asinxron)"""
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
    """Foydalanuvchini bazaga takrorlanmas qilib qo'shish"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, full_name, username)
            VALUES (?, ?, ?)
        """, (user_id, full_name, username))
        await db.commit()

async def get_users_count() -> int:
    """Admin panel uchun foydalanuvchilar sonini aniq hisoblash"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
