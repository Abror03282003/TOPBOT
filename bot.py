import os
import re
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from handlers import start, download

# 1. Railway Variables'dan YOUTUBE_COOKIES matnini olib, cookies.txt yaratish
cookies_data = os.environ.get("YOUTUBE_COOKIES")
if cookies_data:
    # Text formatidagi newline va tab belgilarga ishlov berish
    formatted_cookies = cookies_data.replace("\\n", "\n").replace("\\t", "\t")
    
    # Har bir qatordagi probellarni Netscape TAB formatiga o'tkazish
    cleaned_lines = []
    for line in formatted_cookies.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            cleaned_lines.append(line)
        else:
            parts = re.split(r'\s+', line)
            if len(parts) >= 7:
                cleaned_lines.append("\t".join(parts))
            else:
                cleaned_lines.append(line)
                
    with open("cookies.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(cleaned_lines) + "\n")
    print("✅ cookies.txt fayli muvaffaqiyatli yaratildi.")

# Logging sozlamasi
logging.basicConfig(level=logging.INFO)

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
    
    # Eski webhook update'larni o'chirish va polling boshlash
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
