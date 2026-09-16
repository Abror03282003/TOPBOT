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
                last_active DATE DEFAULT CURRENT_DATE,
                referrer_id INTEGER DEFAULT NULL,
                referrals_count INTEGER DEFAULT 0
            )
        """)
        
        # Audio kesh jadvalini yaratish
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audio_cache (
                youtube_id TEXT PRIMARY KEY,
                file_id TEXT
            )
        """)

        # Konkurs sozlamalari jadvali
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contest_settings (
                id INTEGER PRIMARY KEY DEFAULT 1,
                is_active INTEGER DEFAULT 0,
                target_referrals INTEGER DEFAULT 25,
                prize_amount INTEGER DEFAULT 50000,
                end_time TEXT DEFAULT NULL
            )
        """)
        
        # Boshlang'ich konkurs sozlamasini kiritish (agar bo'lmasa)
        await db.execute("""
            INSERT OR IGNORE INTO contest_settings (id, is_active, target_referrals, prize_amount)
            VALUES (1, 0, 25, 50000)
        """)
        
        # Eski bazalarda ustunlar bo'lmasa, ularni xavfsiz qo'shish
        try:
            await db.execute("ALTER TABLE users ADD COLUMN last_active DATE DEFAULT CURRENT_DATE")
        except Exception:
            pass

        try:
            await db.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
        except Exception:
            pass

        try:
            await db.execute("ALTER TABLE users ADD COLUMN referrals_count INTEGER DEFAULT 0")
        except Exception:
            pass

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
    """Reklama va e'lonlar yuborish uchun barcha user_id larni olish."""
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

# --- REFERAL VA KONKURS FUNKSIYALARI ---

async def get_contest_settings():
    """Konkurs sozlamalarini olish."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_active, target_referrals, prize_amount, end_time FROM contest_settings WHERE id = 1") as cursor:
            res = await cursor.fetchone()
            if res:
                return {
                    "is_active": res[0],
                    "target": res[1],
                    "prize": res[2],
                    "end_time": res[3]
                }
            return {"is_active": 0, "target": 25, "prize": 50000, "end_time": None}

async def update_contest_settings(target: int, prize: int, end_time: str = None, is_active: int = 1):
    """Admin tomonidan konkurs parametrlarini va vaqtni yangilash."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE contest_settings 
            SET target_referrals = ?, prize_amount = ?, end_time = ?, is_active = ?
            WHERE id = 1
        """, (target, prize, end_time, is_active))
        await db.commit()

async def stop_contest_db():
    """Konkursni to'xtatish."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE contest_settings SET is_active = 0 WHERE id = 1")
        await db.commit()

async def process_referral(new_user_id: int, referrer_id: int) -> bool:
    """Yangi foydalanuvchini taklif qilgan odamga referal sifatida biriktirish."""
    if new_user_id == referrer_id:
        return False

    async with aiosqlite.connect(DB_NAME) as db:
        # Foydalanuvchi ilgaridan bormi va kimdir uni taklif qilganmi tekshirish
        async with db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (new_user_id,)) as cursor:
            user = await cursor.fetchone()
            if user and user[0] is not None:
                return False  # Allaqachon boshqa referali bor

        # Taklif qilgan odamning referal hisobini 1 ga oshirish
        await db.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?", (referrer_id,))
        # Yangi foydalanuvchiga taklif qiluvchi ID-sini yozib qo'yish
        await db.execute("UPDATE users SET referrer_id = ? WHERE user_id = ?", (referrer_id, new_user_id))
        await db.commit()
        return True

async def get_leaderboard(limit: int = 10):
    """TOP-10 ko'p referal yig'ganlar reytingini olish."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT full_name, referrals_count FROM users WHERE referrals_count > 0 ORDER BY referrals_count DESC LIMIT ?", 
            (limit,)
        ) as cursor:
            return await cursor.fetchall()

async def get_winner():
    """Eng ko'p referal yig'gan g'olibni aniqlash."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, full_name, referrals_count FROM users ORDER BY referrals_count DESC LIMIT 1") as cursor:
            return await cursor.fetchone()
async def update_contest_announcement(target: int, prize: int, end_time: str, post_text: str, photo_id: str = None):
    """Admin yaratgan konkurs posti ma'lumotlarini saqlash."""
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute("ALTER TABLE contest_settings ADD COLUMN post_text TEXT")
            await db.execute("ALTER TABLE contest_settings ADD COLUMN photo_id TEXT")
        except Exception:
            pass

        await db.execute("""
            UPDATE contest_settings 
            SET target_referrals = ?, prize_amount = ?, end_time = ?, post_text = ?, photo_id = ?, is_active = 1
            WHERE id = 1
        """, (target, prize, end_time, post_text, photo_id))
        await db.commit()

async def get_top3_leaderboard():
    """Top 3 talik yetakchilarni olish"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT full_name, referrals_count FROM users WHERE referrals_count > 0 ORDER BY referrals_count DESC LIMIT 3"
        ) as cursor:
            return await cursor.fetchall()
