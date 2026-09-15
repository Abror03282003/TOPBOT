import os
import shutil
import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, FSInputFile
from shazamio import Shazam
from services.downloader import search_tracks, download_audio_by_id

router = Router()

TEMP_DIR = "downloads"
os.makedirs(TEMP_DIR, exist_ok=True)
shazam = Shazam()

# FFmpeg yo'lini aniqlash
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"


async def convert_to_mp3(input_path: str, output_path: str) -> bool:
    """Audio/Video faylni Shazam uchun MP3 formatiga o'tkazish."""
    if not FFMPEG_PATH:
        return False
    
    cmd = f'"{FFMPEG_PATH}" -y -i "{input_path}" -vn -ar 44100 -ac 2 -b:a 192k "{output_path}"'
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.communicate()
    return proc.returncode == 0


@router.message(F.voice | F.video_note | F.audio)
async def handle_shazam_media(message: Message, bot: Bot):
    status_msg = await message.answer("🔍 Qo'shiq tanib olinmoqda, kuting...")

    media = message.voice or message.video_note or message.audio
    file_id = media.file_id
    raw_file = os.path.join(TEMP_DIR, f"raw_{file_id}")
    converted_file = os.path.join(TEMP_DIR, f"shazam_{file_id}.mp3")

    file_path = None
    try:
        # 1. Telegram serveridan faylni yuklab olamiz
        tg_file = await bot.get_file(file_id)
        await bot.download_file(tg_file.file_path, destination=raw_file)

        # 2. Faylni MP3 ga o'tkazamiz (Shazam to'g'ri o'qishi uchun)
        is_converted = await convert_to_mp3(raw_file, converted_file)
        target_file = converted_file if is_converted else raw_file

        # 3. Shazam orqali tanib olamiz
        out = await shazam.recognize(target_file)
        track = out.get('track')

        if not track:
            await status_msg.edit_text("❌ Afsuski, ushbu audiodan qo'shiqni tanib bo'lmadi.\n💡 <i>Maslahat: Ovozli xabarni kamida 5-8 soniya davomida, qo'shiq aniq eshitiladigan joyidan yuboring.</i>", parse_mode="HTML")
            return

        full_title = f"{track.get('subtitle')} - {track.get('title')}"
        await status_msg.edit_text(f"🎵 Topildi: <b>{full_title}</b>\n⏳ Qo'shiq yuklanmoqda...", parse_mode="HTML")

        # 4. YouTube'dan qidiramiz va yuklaymiz
        search_results = await search_tracks(full_title, limit=1)
        if not search_results:
            await status_msg.edit_text(f"🎵 Topildi: <b>{full_title}</b>\n❌ Lekin yuklab olish uchun fayli topilmadi.", parse_mode="HTML")
            return

        video_id = search_results[0]['id']
        file_path, title = await download_audio_by_id(video_id)

        if file_path and os.path.exists(file_path):
            audio_file = FSInputFile(file_path, filename=f"{full_title}.mp3")
            await message.answer_audio(audio=audio_file, caption=f"🎧 <b>{full_title}</b>", parse_mode="HTML")
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Audio faylni yuklab olishda xatolik yuz berdi.")

    except Exception as e:
        logging.error(f"Shazam xatosi: {e}")
        await status_msg.edit_text("❌ Ishlov berishda kutilmagan xatolik bo'ldi.")

    finally:
        # Barcha vaqtinchalik fayllarni tozalaymiz
        for f in [raw_file, converted_file]:
            if os.path.exists(f):
                os.remove(f)
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
