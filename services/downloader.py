import os
import uuid
import asyncio
import yt_dlp

from config import DOWNLOADS_DIR

os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class DownloadError(Exception):
    pass


def _download_sync(url: str, audio_only: bool = False) -> str:
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
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _download_sync, url, audio_only)


def cleanup_file(filepath: str) -> None:
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except OSError:
        pass
