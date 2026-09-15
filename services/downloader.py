import os
import uuid
import asyncio
import yt_dlp

from config import DOWNLOADS_DIR

os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class DownloadError(Exception):
    pass


def _download_sync(url: str, audio_only: bool = False) -> str:
    """yt-dlp orqali faylni sinxron ravishda yuklaydi. Fayl yo'lini qaytaradi."""
    file_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOADS_DIR, f"{file_id}.%(ext)s")

    if audio_only:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": True,
            "no_warnings": True,
        }
    else:
        ydl_opts = {
            "format": "best[filesize<50M]/best",
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if audio_only:
                filename = os.path.splitext(filename)[0] + ".mp3"
            return filename
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e))


async def download_media(url: str, audio_only: bool = False) -> str:
    """Async wrapper - yt-dlp bloklovchi operatsiyani alohida threadda bajaradi."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _download_sync, url, audio_only)


def _search_sync(query: str, limit: int = 10) -> list:
    """YouTube'dan qo'shiq nomi bo'yicha qidiradi, hech narsani yuklamaydi."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        entries = info.get("entries", []) if info else []

    results = []
    for entry in entries:
        if not entry:
            continue
        duration = entry.get("duration")
        duration_str = ""
        if duration:
            minutes = int(duration) // 60
            seconds = int(duration) % 60
            duration_str = f"{minutes}:{seconds:02d}"
        results.append({
            "id": entry.get("id"),
            "title": entry.get("title", "Noma'lum"),
            "duration": duration_str,
        })
    return results


async def search_media(query: str, limit: int = 10) -> list:
    """Async wrapper - qidiruvni alohida threadda bajaradi."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _search_sync, query, limit)


def cleanup_file(filepath: str) -> None:
    """Yuborilgan faylni serverdan o'chirish."""
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except OSError:
        pass
