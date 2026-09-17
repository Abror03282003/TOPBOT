import os
import asyncio
import subprocess
import logging
from shazamio import Shazam

# downloader.py da aniqlangan FFmpeg yo'lini qayta ishlatamiz
try:
    from services.downloader import FFMPEG_PATH
except Exception:
    import shutil
    FFMPEG_PATH = shutil.which("ffmpeg")
    if not FFMPEG_PATH:
        try:
            import imageio_ffmpeg
            FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            FFMPEG_PATH = "ffmpeg"


async def _run_ffmpeg(args: list) -> None:
    proc = await asyncio.create_subprocess_exec(
        FFMPEG_PATH, *args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logging.warning(f"FFmpeg xatosi: {stderr.decode(errors='ignore')[-500:]}")


async def identify_track(input_file_path: str) -> str | None:
    """
    Ixtiyoriy media fayldan (video, voice, audio note)
    12 soniyalik parcha kesib olib, Shazam orqali qo'shiqni aniqlaydi.
    """
    sample_wav = f"{input_file_path}_sample.wav"

    try:
        if not FFMPEG_PATH:
            logging.error("FFmpeg mavjud emas — Shazam ishlamaydi.")
            return None

        # 2-soniyadan boshlab 12 soniyalik Mono/44.1kHz WAV
        await _run_ffmpeg([
            "-y", "-ss", "00:00:02", "-i", input_file_path,
            "-t", "12", "-vn", "-ac", "1", "-ar", "44100", "-f", "wav", sample_wav
        ])

        # Agar fayl 2 soniyadan qisqa bo'lsa — boshidan kesamiz
        if not os.path.exists(sample_wav) or os.path.getsize(sample_wav) == 0:
            await _run_ffmpeg([
                "-y", "-i", input_file_path,
                "-t", "12", "-vn", "-ac", "1", "-ar", "44100", "-f", "wav", sample_wav
            ])

        if not os.path.exists(sample_wav) or os.path.getsize(sample_wav) == 0:
            return None

        shazam = Shazam()
        out = await shazam.recognize(sample_wav)

        track = out.get('track')
        if track:
            title = track.get('title', '')
            subtitle = track.get('subtitle', '')
            return f"{subtitle} - {title}".strip(" -")

        return None

    except Exception as e:
        logging.error(f"Shazam error: {e}")
        return None
    finally:
        if os.path.exists(sample_wav):
            os.remove(sample_wav)
