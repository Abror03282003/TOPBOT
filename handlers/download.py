import os
from aiogram import Router, F
from aiogram.types import Message, FSInputFile
from services.downloader import search_tracks, download_media, download_audio_by_id

router = Router()

@router.message(F.text.startswith("http"))
async def handle_link(message: Message):
    msg = await message.answer("⏳ Video yuklanmoqda...")
    try:
        data = await download_media(message.text)
        file_path = data.get("file_path")
        
        if file_path and os.path.exists(file_path):
            video_file = FSInputFile(file_path)
            await message.answer_video(
                video=video_file, 
                caption=data.get("title", "")[:1024]
            )
            os.remove(file_path)
            await msg.delete()
        else:
            await msg.edit_text("❌ Fayl topilmadi.")
    except Exception as e:
        await msg.edit_text(f"❌ Yuklashda xatolik yuz berdi: {e}")


@router.message(F.text.startswith("/dl_"))
async def handle_download_audio(message: Message):
    track_id = message.text.replace("/dl_", "").strip()
    msg = await message.answer("⏳ Qo'shiq yuklanmoqda...")
    try:
        file_path, title = await download_audio_by_id(track_id)
        if file_path and os.path.exists(file_path):
            audio_file = FSInputFile(file_path)
            await message.answer_audio(
                audio=audio_file,
                title=title
            )
            os.remove(file_path)
            await msg.delete()
        else:
            await msg.edit_text("❌ Audio fayl topilmadi.")
    except Exception as e:
        await msg.edit_text(f"❌ Audio yuklashda xatolik: {e}")


@router.message(F.text)
async def handle_search(message: Message):
    msg = await message.answer("🔍 Qidirilmoqda...")
    try:
        results = await search_tracks(message.text)
        if not results:
            await msg.edit_text("❌ Hech narsa topilmadi.")
            return
        
        text = "<b>🔍 Topilgan qo'shiqlar:</b>\n\n"
        for i, item in enumerate(results[:5], 1):
            text += f"{i}. <b>{item['title']}</b> ({item['uploader']})\n"
            text += f"   /dl_{item['id']}\n\n"
            
        await msg.edit_text(text, parse_mode="HTML")
    except Exception as e:
        await msg.edit_text(f"❌ Qidiruvda xatolik: {e}")
