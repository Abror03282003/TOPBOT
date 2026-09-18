import os
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message
from services.shazam import recognize_audio
from services.downloader import search_tracks, download_audio_by_id
from database import save_to_cache

router = Router()

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

@router.message(F.voice | F.audio | F.video)
async def handle_shazam_media(message: Message, bot: Bot):
    status_msg = await message.answer("🔍 Qo'shiq eshitilmoqda va qidirilmoqda...")
    
    file_id = None
    if message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id
    elif message.video:
        file_id = message.video.file_id

    if not file_id:
        await status_msg.edit_text("❌ Faylni yuklab bo'lmadi.")
        return

    local_path = os.path.join(DOWNLOAD_DIR, f"shazam_{message.from_user.id}_{message.message_id}.ogg")
    
    try:
        # Faylni Telegram serveridan yuklab olish
        file_info = await bot.get_file(file_id)
        await bot.download_file(file_info.file_path, destination=local_path)

        # Shazam orqali tanib olish
        track_info = await recognize_audio(local_path)
        
        if not track_info:
            await status_msg.edit_text("😔 Afsuski, bu qo'shiqni aniqlay olmadim.")
            return

        await status_msg.edit_text(f"🎵 Topildi: **{track_info['artist']} - {track_info['title']}**\n\nYuklanmoqda...")

        # Topilgan nom bo'yicha YouTube'dan qidirish
        search_results = await search_tracks(track_info['query'], limit=1)
        
        if not search_results:
            await status_msg.edit_text(f"🎵 Topildi: **{track_info['query']}**\n\nLekin yuklab olish uchun audio fayli topilmadi.")
            return

        video_id = search_results[0]['id']
        file_path, title, cached_file_id = await download_audio_by_id(video_id)

        if cached_file_id:
            await message.answer_audio(audio=cached_file_id, caption=f"🎵 {title}\n\n🤖 @top_botuz_bot")
            await status_msg.delete()
        elif file_path and os.path.exists(file_path):
            sent_audio = await message.answer_audio(
                audio=FSInputFile(file_path),
                caption=f"🎵 {title}\n\n🤖 @top_botuz_bot"
            )
            await save_to_cache(video_id, sent_audio.audio.file_id)
            await status_msg.delete()
            if os.path.exists(file_path):
                os.remove(file_path)
        else:
            await status_msg.edit_text("❌ Qo'shiqni yuklab bo'lmadi.")

    except Exception as e:
        logging.error(f"Shazam handler xatosi: {e}")
        await status_msg.edit_text("❌ Xatolik yuz berdi.")
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)
