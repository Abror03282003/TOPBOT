import os
import shutil
import asyncio
import logging

# 1. FFmpeg yo'lini pydub import bo me'moriy bo'lishidan oldin PATH ga qo'shish
ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
if os.path.exists(ffmpeg_bin):
    os.environ["PATH"] += os.pathsep + os.path.dirname(ffmpeg_bin)
else:
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        os.environ["PATH"] += os.pathsep + os.path.dirname(ffmpeg_bin)
    except Exception:
        pass

# 2. Qolgan kutubxona va modullarni import qilish
from aiogram import Bot, Dispatcher
from database import init_db
from handlers import start, download, admin, referral

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# COOKIES QISMI AYNAN SIZDAGIDAIK O'ZGARISHSZ QOLDIRILDI:
YOUTUBE_COOKIES = os.environ.get("YOUTUBE_COOKIES")
if YOUTUBE_COOKIES:
    with open("cookies.txt", "w") as f:
        f.write(YOUTUBE_COOKIES)

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # Ma'lumotlar bazasini asinxron ishga tushirish (users va audio_cache jadvallarini yaratadi)
    await init_db()
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Routerlarni ulash
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(referral.router)
    dp.include_router(download.router)

    logging.info("Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
