import os
import re
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from handlers import start, download

# Logging sozlamasi
logging.basicConfig(level=logging.INFO)

# 1. Railway Variables'dan cookies faylini to'g'ri formatda yaratish
raw_cookies = os.getenv("YOUTUBE_COOKIES")
if raw_cookies:
    lines = raw_cookies.strip().splitlines()
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            cleaned_lines.append(line)
        else:
            # Probellarni TAB formatiga o'tkazish
            parts = re.split(r'\s+', line)
            if len(parts) >= 7:
                cleaned_lines.append("\t".join(parts))
            else:
                cleaned_lines.append(line)
    
    with open("cookies.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(cleaned_lines) + "\n")
    print("✅ cookies.txt fayli muvaffaqiyatli yaratildi.")

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def main():
    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    
    # Routerlarni ulash
    dp.include_router(start.router)
    dp.include_router(download.router)
    
    # Eski update'larni o'chirish va polling boshlash
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
if __name__ == "__main__":
    asyncio.run(main())
