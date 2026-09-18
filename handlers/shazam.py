import os
import logging
from aiogram import Router, F, types, Bot
from services.shazam import recognize_song
from services.downloader import search_tracks, download_audio_by_id

router = Router()

@router.message(F.voice | F.video_note | F.audio | F.video)
async def handle_shazam_media(message: types.Message, bot: Bot):
    msg = await message.answer("🔍 Media tahlil qilinmoqda, musiqa qidirilmoqda...")
    
    # Media turini aniqlash
    if message.voice:
        file_id = message.voice.file_id
        ext = "ogg"
    elif message.video_note:
        file_id = message.video_note.file_id
        ext = "mp4"
    elif message.audio:
        file_id = message.audio.file_id
        ext = "mp3"
    elif message.video:
        file_id = message.video.file_id
        ext = "mp4"
    else:
        await msg.edit_text("❌ Qo'llab-quvvatlanmaydigan fayl.")
        return

    file_path = f"downloads/shazam_{file_id}.{ext}"

    try:
        file_info = await bot.get_file(file_id)
        await bot.download_file(file_info.file_path, file_path)

        # services/shazam.py orqali aniqlash
        song_info = await recognize_song(file_path)
    except Exception as e:
        logging.error(f"Shazam yuklash/aniqlash xatosi: {e}")
        song_info = None
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    if not song_info:
        await msg.edit_text("❌ Afsuski, ushbu mediadan musiqa topilmadi.")
        return

    # Ba'zan shazam service dict o'rniga string yoki tuple qaytarishi mumkin, shuni tekshirish:
    if isinstance(song_info, dict):
        query = f"{song_info.get('artist', '')} - {song_info.get('title', '')}".strip(" -")
    else:
        query = str(song_info)

    await msg.edit_text(f"🎧 Topildi: **{query}**\n\n⬇️ Qo'shiq yuklanmoqda...")

    # Izlash va yuklab berish
    tracks = await search_tracks(query, limit=1)
    if tracks:
        res = await download_audio_by_id(tracks[0]['id'])
        file_path = res[0] if isinstance(res, tuple) else res
        cached_id = res[2] if isinstance(res, tuple) and len(res) > 2 else None

        if cached_id:
            await message.answer_audio(cached_id, caption=f"🎵 {query}")
            await msg.delete()
        elif file_path and os.path.exists(file_path):
            await message.answer_audio(
                audio=types.FSInputFile(file_path),
                caption=f"🎵 {query}"
            )
            await msg.delete()
            os.remove(file_path)
        else:
            await msg.edit_text(f"🎵 Topildi: **{query}**\n❌ Qo'shiqni yuklab bo'lmadi.")
    else:
        await msg.edit_text(f"🎵 Topildi: **{query}**\n❌ Manba topilmadi.")
