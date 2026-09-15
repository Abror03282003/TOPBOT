import os
import uuid
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from services.downloader import search_tracks, download_media, download_audio_by_id

router = Router()

# Qidiruv kesh xotirasi (uzun URL'larni tugmaga sig'dirish uchun)
SEARCH_CACHE = {}

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


@router.message(F.text)
async def handle_search(message: Message):
    msg = await message.answer("🔍 Qidirilmoqda...")
    try:
        results = await search_tracks(message.text)
        if not results:
            await msg.edit_text("❌ Hech narsa topilmadi.")
            return
        
        keyboard = []
        text = "<b>🔍 Topilgan qo'shiqlar:</b>\n\n"
        
        for i, item in enumerate(results[:5], 1):
            # Har bir trek uchun qisqa unikal kalit yaratamiz
            cache_id = str(uuid.uuid4())[:8]
            SEARCH_CACHE[cache_id] = item['id']
            
            text += f"{i}. <b>{item['title']}</b> ({item['uploader']})\n\n"
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🎵 {i}. {item['title'][:30]} - Yuklash", 
                    callback_data=f"dl_{cache_id}"
                )
            ])
            
        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await msg.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        await msg.edit_text(f"❌ Qidiruvda xatolik: {e}")


@router.callback_query(F.data.startswith("dl_"))
async def handle_download_callback(call: CallbackQuery):
    cache_id = call.data.replace("dl_", "")
    track_url = SEARCH_CACHE.get(cache_id)
    
    if not track_url:
        await call.answer("❌ Fayl kaliti eskirgan. Qaytadan qidiring.", show_alert=True)
        return

    await call.answer("⏳ Yuklash boshlandi...")
    status_msg = await call.message.answer("⏳ Qo'shiq yuklanmoqda va tayyorlanmoqda...")
    
    try:
        file_path, title = await download_audio_by_id(track_url)
        if file_path and os.path.exists(file_path):
            audio_file = FSInputFile(file_path)
            await call.message.answer_audio(
                audio=audio_file,
                title=title
            )
            os.remove(file_path)
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Audio fayl topilmadi.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Audio yuklashda xatolik: {e}")
