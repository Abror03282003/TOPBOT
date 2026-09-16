import os
import asyncio
import logging
from aiogram import Bot, Dispatcher
from database import init_db
from handlers import download, admin

# Environment orqali token va cookies sozlamasini olish
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# YouTube cookies sozlamasi (Railway uchun)
YOUTUBE_COOKIES = os.environ.get("YOUTUBE_COOKIES")
if YOUTUBE_COOKIES:
    with open("cookies.txt", "w") as f:
        f.write(YOUTUBE_COOKIES)

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # Ma'lumotlar bazasini asinxron ishga tushirish
    await init_db()
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Routerlarni ulash
    dp.include_router(admin.router)
    dp.include_router(download.router)  # Barcha yuklash, qidiruv va audio/video tanish shu yerda

    logging.info("Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
