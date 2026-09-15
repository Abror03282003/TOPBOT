from aiogram import Router, F
from aiogram.types import Message
from services.downloader import search_tracks, download_media

router = Router()

@router.message(F.text.startswith("http"))
async def handle_link(message: Message):
    msg = await message.answer("⏳ Yuklanmoqda...")
    try:
        data = await download_media(message.text)
        await message.answer_video(
            video=data["file_path"], 
            caption=data.get("title", "")
        )
        await msg.delete()
    except Exception as e:
        # Aniq xatolik matnini Telegram'da ko'rish uchun:
        await msg.edit_text(f"❌ Yuklashda xatolik yuz berdi: {e}")

@router.message(F.text)
async def handle_search(message: Message):
    msg = await message.answer("🔍 Qidirilmoqda...")
    try:
        results = await search_tracks(message.text)
        if not results:
            await msg.edit_text("❌ Hech narsa topilmadi.")
            return
        
        # Qidiruv natijalarini chiqarish kodingiz...
        await msg.edit_text(f"✅ {len(results)} ta natija topildi!")
    except Exception as e:
        # Aniq xatolik matnini Telegram'da ko'rish uchun:
        await msg.edit_text(f"❌ Qidiruvda xatolik: {e}")
