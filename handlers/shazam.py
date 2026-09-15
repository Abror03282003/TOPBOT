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

def get_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"

FFMPEG_PATH = get_ffmpeg()


async def convert_to_wav(input_path: str, output_path: str) -> bool:
    """Ovoz/Video faylini Shazam tushunadigan 16kHz WAV formatiga o'tkazadi."""
    if not FFMPEG_PATH:
        logging.error("FFmpeg topilmadi!")
        return False
    
    cmd = f'"{FFMPEG_PATH}" -y -i "{input_path}" -vn -acodec pcm_s16le -ac 1 -ar 16000 "{output_path}"'
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        logging.error(f"FFmpeg conversion error: {stderr.decode()}")
        return False
    return True


@router.message(F.voice | F.video_note | F.audio)
async def handle_shazam_media(message: Message, bot: Bot):
    status_msg = await message.answer("🔍 Qo'shiq tanib olinmoqda, kuting...")

    media = message.voice or message.video_note or message.audio
    
    # Qisqa audiolarni filtrlash
    duration = getattr(media, 'duration', 0)
    if duration > 0 and duration < 3:
        await status_msg.edit_text("❌ Ovozli xabar juda qisqa!\n💡 Qo'shiqni tanib olish uchun kamida 4-7 soniya yuboring.")
        return

    file_id = media.file_id
    raw_file = os.path.join(TEMP_DIR, f"raw_{file_id}")
    converted_wav = os.path.join(TEMP_DIR, f"shazam_{file_id}.wav")

    downloaded_file_path = None
    try:
        # Telegram'dan yuklab olish
        tg_file = await bot.get_file(file_id)
        await bot.download_file(tg_file.file_path, destination=raw_file)

        # WAV formatga o'tkazish
        is_converted = await convert_to_wav(raw_file, converted_wav)
        target_file = converted_wav if is_converted else raw_file

        # Shazam orqali qidirish
        out = await shazam.recognize(target_file)
        track = out.get('track')

        if not track:
            await status_msg.edit_text(
                "❌ Afsuski, ushbu audiodan qo'shiqni tanib bo'lmadi.\n\n"
                "💡 <b>Maslahat:</b> Qo'shiq eshitilayotgan manbaga mikrofonni yaqinroq tutib, kamida <b>6-8 soniya</b> yuboring.",
                parse_mode="HTML"
            )
            return

        artist = track.get('subtitle', '')
        song = track.get('title', '')
        full_title = f"{artist} - {song}" if artist else song

        await status_msg.edit_text(f"🎵 Topildi: <b>{full_title}</b>\n⏳ Qo'shiq yuklanmoqda...", parse_mode="HTML")

        # YouTube'dan qidirish va yuklab olish
        search_results = await search_tracks(full_title, limit=1)
        if not search_results:
            await status_msg.edit_text(f"🎵 Topildi: <b>{full_title}</b>\n❌ Lekin yuklab olish uchun fayli topilmadi.", parse_mode="HTML")
            return

        video_id = search_results[0]['id']
        downloaded_file_path, title = await download_audio_by_id(video_id)

        if downloaded_file_path and os.path.exists(downloaded_file_path):
            audio_file = FSInputFile(downloaded_file_path, filename=f"{full_title}.mp3")
            await message.answer_audio(audio=audio_file, caption=f"🎧 <b>{full_title}</b>", parse_mode="HTML")
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Audio fayl topilmadi yoki yuklab olishda xatolik bo'ldi.")

    except Exception as e:
        logging.error(f"Shazam handler error: {e}")
        await status_msg.edit_text("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.")

    finally:
        for path in [raw_file, converted_wav]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        if downloaded_file_path and os.path.exists(downloaded_file_path):
            try:
                os.remove(downloaded_file_path)
            except Exception:
                pass
