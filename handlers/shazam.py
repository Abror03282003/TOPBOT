import os
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, FSInputFile
from services.shazam import recognize_audio
from services.downloader import search_tracks, download_audio_by_id

router = Router()

TEMP_DIR = "downloads"
os.makedirs(TEMP_DIR, exist_ok=True)


@router.message(F.voice | F.video_note | F.audio)
async def handle_shazam_media(message: Message, bot: Bot):
    status_msg = await message.answer("🔍 Qo'shiq tanib olinmoqda, kuting...")

    # Qaysi turdagi fayl kelganini aniqlaymiz
    media = message.voice or message.video_note or message.audio
    file_id = media.file_id
    file_ext = "ogg" if message.voice else ("mp4" if message.video_note else "mp3")
    local_file = os.path.join(TEMP_DIR, f"shazam_{file_id}.{file_ext}")

    try:
        # 1. Telegram serveridan faylni lokal papkaga yuklab olamiz
        tg_file = await bot.get_file(file_id)
        await bot.download_file(tg_file.file_path, destination=local_file)

        # 2. Shazam orqali qo'shiqni tanib olamiz
        track_info = await recognize_audio(local_file)

        if not track_info:
            await status_msg.edit_text("❌ Afsuski, ushbu audiodan qo'shiqni tanib bo'lmadi.")
            return

        full_title = track_info['full_title']
        await status_msg.edit_text(f"🎵 Topildi: <b>{full_title}</b>\n⏳ YouTube'dan yuklanmoqda...", parse_mode="HTML")

        # 3. Topilgan qo'shiq nomi bo'yicha YouTube'dan ID'sini qidiramiz
        search_results = await search_tracks(full_title, limit=1)
        if not search_results:
            await status_msg.edit_text(f"🎵 Topildi: <b>{full_title}</b>\n❌ Lekin YouTube'dan fayli topilmadi.", parse_mode="HTML")
            return

        video_id = search_results[0]['id']

        # 4. Qo'shiqni yuklab olib foydalanuvchiga yuboramiz
        file_path, title = await download_audio_by_id(video_id)

        if file_path and os.path.exists(file_path):
            audio_file = FSInputFile(file_path, filename=f"{full_title}.mp3")
            await message.answer_audio(audio=audio_file, caption=f"🎧 <b>{full_title}</b>", parse_mode="HTML")
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Qo'shiqni yuklab olishda xatolik yuz berdi.")

    except Exception as e:
        logging.error(f"Shazam handler xatosi: {e}")
        await status_msg.edit_text("❌ Qayta ishlashda kutilmagan xatolik yuz berdi.")

    finally:
        # Har qanday holatda ham vaqtinchalik xotiradagi faylni o'chiramiz
        if os.path.exists(local_file):
            os.remove(local_file)
        if 'file_path' in locals() and file_path and os.path.exists(file_path):
            os.remove(file_path)
