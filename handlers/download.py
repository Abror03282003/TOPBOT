import os
from aiogram import Router, F, types
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from utils.url_validator import is_valid_url
from services.downloader import download_media, search_tracks, download_audio_by_id

router = Router()

@router.message(F.text)
async def process_user_input(message: types.Message):
    user_text = message.text.strip()

    # 1. Agar foydalanuvchi LINK yuborgan bo'lsa (Instagram, YouTube, etc.)
    if is_valid_url(user_text):
        status_msg = await message.answer("📥 Video yuklanmoqda, kuting...")
        try:
            data = await download_media(user_text)
            file_path = data["file_path"]

            if os.path.exists(file_path):
                video = FSInputFile(file_path)
                
                # Videoni va uning ostida MP3 ajratib olish tugmasini birga yuboramiz
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(
                            text="🎵 Audiosini (MP3) yuklab olish", 
                            callback_data=f"audio_{data['id']}"
                        )
                    ]]
                )
                await message.answer_video(video=video, caption=f"🎬 {data['title']}", reply_markup=keyboard)
                os.remove(file_path)
                await status_msg.delete()
            else:
                await status_msg.edit_text("❌ Videoni saqlab bo'lmadi.")
        except Exception as e:
            await status_msg.edit_text(f"❌ Yuklashda xatolik yuz berdi: {str(e)}")

    # 2. Agar foydalanuvchi QO'SHIQ NOMI yozgan bo'lsa
    else:
        status_msg = await message.answer("🔍 Qidirilmoqda, kuting...")
        try:
            tracks = await search_tracks(user_text, limit=10)
            if not tracks:
                await status_msg.edit_text("❌ Hech narsa topilmadi.")
                return

            buttons = []
            for idx, track in enumerate(tracks, 1):
                # Callback data ga trekning aniq ID siga havola biriktiramiz
                buttons.append([
                    InlineKeyboardButton(
                        text=f"{idx}. {track['title'][:35]}", 
                        callback_data=f"song_{track['id']}"
                    )
                ])

            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await status_msg.edit_text("👇 Yuklab olmoqchi bo'lgan qo'shiqni tanlang:", reply_markup=keyboard)
        except Exception as e:
            await status_msg.edit_text(f"❌ Qidiruvda xatolik: {str(e)}")


# Qo'shiq raqami yoki MP3 tugmasi bosilganda ishlaydigan Handler
@router.callback_query(F.data.startswith("song_") | F.data.startswith("audio_"))
async def process_song_download(callback: types.CallbackQuery):
    await callback.answer("🎵 Qo'shiq tayyorlanmoqda...")
    
    # Prefixni olib tashlab video ID sini olamiz
    if callback.data.startswith("song_"):
        media_id = callback.data.split("song_")[1]
    else:
        media_id = callback.data.split("audio_")[1]

    status_msg = await callback.message.answer("📥 MP3 yuklanmoqda...")

    try:
        file_path, title = await download_audio_by_id(media_id)
        if os.path.exists(file_path):
            audio = FSInputFile(file_path)
            await callback.message.answer_audio(audio=audio, title=title)
            
            os.remove(file_path) # Faylni o'chirish
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Audio faylni topib bo'lmadi.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Qo'shiqni yuklashda xatolik: {str(e)}")
