import os
import glob
import shutil
import asyncio
import logging
import urllib.parse
import yt_dlp

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = shutil.which("ffmpeg") or shutil.which("ffprobe") or "/usr/bin/ffmpeg"

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIES_PATH = "cookies.txt"

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'geo_bypass': True,
}

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH


def _get_active_opts(extra_opts: dict) -> dict:
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
    """YouTube va SoundCloud orqali 30 tagacha qo'shiqni qidiradi."""
    search_opts = _get_active_opts({
        'extract_flat': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web']
            }
        }
    })

    def _search():
        # 1-urinish: YouTube bo'yicha (30 ta)
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
                if results:
                    return results
        except Exception as e:
            logging.error(f"YouTube search error: {e}")

        # 2-urinish: SoundCloud bo'yicha (YouTube ishlamay qolganda)
        try:
            sc_opts = _get_active_opts({'extract_flat': True})
            with yt_dlp.YoutubeDL(sc_opts) as ydl:
                res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
                results = []
                if res and 'entries' in res and res['entries']:
                    for entry in res['entries']:
                        if entry:
                            url_or_id = entry.get('url') or entry.get('webpage_url') or entry.get('id')
                            results.append({
                                'id': url_or_id,
                                'title': entry.get('title', 'Unknown Title'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader', 'Unknown Artist')
                            })
                return results
        except Exception as e:
            logging.error(f"SoundCloud search error: {e}")
            return []

    return await asyncio.to_thread(_search)


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str]:
    """YouTube ID yoki SoundCloud URL orqali audio yuklab olish."""
    if str(video_id_or_url).startswith("http"):
        url = video_id_or_url
        file_prefix = "sc_" + str(hash(video_id_or_url))[-6:]
    else:
        url = f"https://www.youtube.com/watch?v={video_id_or_url}"
        file_prefix = video_id_or_url

    ydl_opts = _get_active_opts({
        'format': 'bestaudio/best',
        'outtmpl': f'{DOWNLOAD_DIR}/{file_prefix}.%(ext)s',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web']
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
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    title = info.get('title', 'Audio Track')
        except Exception as e:
            logging.error(f"Download error: {e}")

        # 1. Aniq kutilgan MP3 faylini tekshirish
        expected_mp3 = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")
        if os.path.exists(expected_mp3) and os.path.getsize(expected_mp3) > 0:
            return expected_mp3, title

        # 2. Prefiks bo'yicha saqlangan har qanday faylni qidirish
        pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
        files = glob.glob(pattern)
        for f in files:
            if os.path.getsize(f) > 0:
                return f, title

        # 3. Oxirgi chora: Oxirgi tushgan faylni olish
        all_files = glob.glob(os.path.join(DOWNLOAD_DIR, "*"))
        if all_files:
            latest_file = max(all_files, key=os.path.getmtime)
            if os.path.getsize(latest_file) > 0:
                return latest_file, title

        return None, title

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    """Video yuklab olish (YouTube/Instagram)"""
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
