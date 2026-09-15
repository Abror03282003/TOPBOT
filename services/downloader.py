import os
import glob
import shutil
import asyncio
import logging
import yt_dlp

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = shutil.which("ffmpeg") or shutil.which("ffprobe") or "/usr/bin/ffmpeg"

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIES_PATH = "cookies.txt"

# Anti-bot va blokirovkaga tushmaslik sozlamalari
BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'geo_bypass': True,
}

if FFMPEG_PATH:
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH


def _get_active_opts(extra_opts: dict) -> dict:
    """Cookies fayli borligini dinamik tekshirib, opsiyalarni beradi."""
    opts = {**BASE_YDL_OPTS, **extra_opts}
    if os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0:
        opts['cookiefile'] = COOKIES_PATH
    return opts


def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    search_opts = _get_active_opts({
        'extract_flat': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['configs']
            }
        }
    })

    def _search():
        try:
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                results = []
                if res and 'entries' in res and res['entries']:
                    for entry in res['entries']:
                        if entry and entry.get('id'):
                            results.append({
                                'id': entry.get('id'),
                                'title': entry.get('title', 'Unknown Title'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader', 'Unknown Artist')
                            })
                return results
        except Exception as e:
            logging.error(f"Search error: {e}")
            return []

    return await asyncio.to_thread(_search)


async def download_audio_by_id(video_id: str) -> tuple[str | None, str]:
    """MP3 formatida yuklab olish (xatoliklarsiz va moslashuvchan format bilan)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    ydl_opts = _get_active_opts({
        # FORMAT MOSLASHUVCHAN QILINDI: bestaudio bolmasa, oddiy eng past sifatli videodan bo'lsa ham audioni ajratadi
        'format': 'bestaudio/bestaudio*/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    })

    def _download():
        title = "Audio Track"
        file_id = video_id

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info and isinstance(info, dict):
                    title = info.get('title', 'Audio Track')
                    file_id = info.get('id', video_id)
                else:
                    logging.error(f"yt-dlp info ololmadi: {url}")
        except Exception as e:
            logging.error(f"Download error: {e}")

        # Tayyor mp3 faylini tekshiramiz
        expected_mp3 = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp3")
        if os.path.exists(expected_mp3):
            return expected_mp3, title

        # MP3 bo'lmasa, har qanday hosil bo'lgan media faylini olamiz
        pattern = os.path.join(DOWNLOAD_DIR, f"{file_id}.*")
        files = glob.glob(pattern)
        if files:
            return files[0], title

        return None, title

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    ydl_opts = _get_active_opts({
        'format': 'best[ext=mp4]/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'max_filesize': 50 * 1024 * 1024,
    })

    def _download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    filename = ydl.prepare_filename(info)
                    return {
                        "file_path": filename,
                        "title": info.get("title", "Video"),
                        "id": info.get("id")
                    }
        except Exception as e:
            logging.error(f"Media download error: {e}")

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
