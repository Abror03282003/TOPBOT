import os
import shutil
import asyncio
import logging

# 1. FFmpeg va FFprobe yo'llarini aniqlash va PATH ga qo'shish
ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
ffmpeg_dir = None

if os.path.exists(ffmpeg_bin):
    ffmpeg_dir = os.path.dirname(ffmpeg_bin)
else:
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(ffmpeg_bin)
    except Exception:
        pass

if ffmpeg_dir:
    os.environ["PATH"] += os.pathsep + ffmpeg_dir

# 2. Pydub sozlamalariga FFmpeg va FFprobe ni to'g'ridan-to'g'ri biriktirish (Warning xatosini yo'qotish uchun)
try:
    from pydub import AudioSegment
    if ffmpeg_bin:
        AudioSegment.converter = ffmpeg_bin
        ffprobe_bin = os.path.join(ffmpeg_dir, "ffprobe") if ffmpeg_dir else "ffprobe"
        AudioSegment.ffprobe = ffprobe_bin if os.path.exists(ffprobe_bin) else ffmpeg_bin
except Exception:
    pass

# 3. Qolgan kutubxona va modullarni import qilish
from aiogram import Bot, Dispatcher
from database import init_db
from handlers import start, download, admin, referral

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# COOKIES QISMI:
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
if __name__ == "__main__":
    asyncio.run(main())
