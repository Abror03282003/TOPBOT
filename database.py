import sqlite3

DB_PATH = "bot_database.db"

def init_db():
    """Ma'lumotlar bazasini yaratish va jadvallarni sozlash."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def add_user(user_id: int, full_name: str, username: str):
    """Yangi foydalanuvchini bazaga qo'shish."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, full_name, username)
        VALUES (?, ?, ?)
    """, (user_id, full_name, username))
    conn.commit()
    conn.close()

def get_total_users() -> int:
    """Jami foydalanuvchilar sonini olish."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_user_ids() -> list[int]:
    """Barcha foydalanuvchilar ID ro'yxatini olish (reklama yuborish uchun)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users
