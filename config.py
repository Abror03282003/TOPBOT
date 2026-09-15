import os

# Railway'da bu qiymatlar "Variables" bo'limida sozlanadi.
# Lokal test uchun .env fayl yoki muhit o'zgaruvchisi ishlatiladi.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Yuklab olingan fayllar vaqtincha shu papkada saqlanadi
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

# Telegram bot API orqali yuborish mumkin bo'lgan maksimal fayl hajmi (baytlarda)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi! Railway'da Variables bo'limiga BOT_TOKEN qo'shing "
        "yoki lokal ishga tushirishda muhit o'zgaruvchisi sifatida bering."
    )
