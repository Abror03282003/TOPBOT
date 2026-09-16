import aiosqlite
from datetime import datetime

DB_NAME = "bot_database.db"

async def init_db():
    """Baza va jadvallarni asinxron yaratish hamda ustunlarni yangilash."""
    async with aiosqlite.connect(DB_NAME) as db:
        # Users jadvalini yaratish
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active DATE DEFAULT CURRENT_DATE
            )
        """)
        
        # Audio kesh jadvalini yaratish
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audio_cache (
                youtube_id TEXT PRIMARY KEY,
                file_id TEXT
            )
        """)
        
        # Agar eski bazada last_active ustuni bo'lmasa, uni xavfsiz qo'shish
        try:
            await db.execute("ALTER TABLE users ADD COLUMN last_active DATE DEFAULT CURRENT_DATE")
        except Exception:
            pass  # Ustun allaqachon mavjud bo'lsa, xatolikni o'tkazib yuboradi

        await db.commit()

async def add_user(user_id: int, full_name: str, username: str = None):
    """Foydalanuvchini bazaga qo'shish va bugungi faolligini yangilash."""
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users (user_id, full_name, username, last_active)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                full_name = excluded.full_name,
                username = excluded.username,
                last_active = excluded.last_active
        """, (user_id, full_name, username, today))
        await db.commit()

async def get_total_users() -> int:
    """Jami botga start bosgan foydalanuvchilar soni."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(user_id) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_today_active_users() -> int:
    """Bugun botdan foydalangan faol foydalanuvchilar soni."""
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(user_id) FROM users WHERE last_active = ?", (today,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_all_user_ids() -> list[int]:
    """Reklama yuborish uchun barcha user_id larni olish (admin.py uchun)."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

# --- KESH FUNKSIYALARI ---

async def get_cached_file(youtube_id: str):
    """Keshdan audio file_id sini olish."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id FROM audio_cache WHERE youtube_id = ?", (youtube_id,)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None

async def save_to_cache(youtube_id: str, file_id: str):
    """Audioni keshga saqlash."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO audio_cache (youtube_id, file_id) VALUES (?, ?)", 
            (youtube_id, file_id)
        )
        await db.commit()
