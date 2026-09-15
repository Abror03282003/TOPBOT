import os
import shutil
import asyncio
import yt_dlp

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# FFmpeg dasturini tizimdan izlash
FFMPEG_PATH = shutil.which("ffmpeg") or shutil.which("ffprobe") or "/root/.nix-profile/bin/ffmpeg" or "/usr/bin/ffmpeg"
COOKIES_PATH = "cookies.txt"

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'nocheckcertificate': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios', 'mweb'],
            'player_skip': ['configs', 'webpage']
        }
    }
}

# FFmpeg mavjud bo'lsa biriktirish
if FFMPEG_PATH:
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH

# Cookies fayli mavjud va bo'sh bo'lmasa biriktirish
if os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0:
    BASE_YDL_OPTS['cookiefile'] = COOKIES_PATH


async def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """Qo'shiq nomi bo'yicha qidiruv (YouTube va SoundCloud fallback)."""
    ydl_opts = {
        **BASE_YDL_OPTS,
        'extract_flat': True,
        'default_search': f'ytsearch{limit}',
    }
    
    def _search():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            results = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry:
                        results.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Unknown Title'),
                            'duration': entry.get('duration', 0),
                            'uploader': entry.get('uploader', 'Unknown Artist')
                        })
            return results

    try:
        res = await asyncio.to_thread(_search)
        if res:
            return res
        raise Exception("YouTube empty results")
    except Exception:
        # YouTube blok berganda SoundCloud orqali qidiruv
        ydl_opts['default_search'] = f'scsearch{limit}'
        def _sc_search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
                results = []
                if res and 'entries' in res:
                    for entry in res['entries']:
                        if entry:
                            results.append({
                                'id': entry.get('url') or entry.get('id'),
                                'title': entry.get('title', 'Unknown Title'),
                                'duration': entry.get('duration', 0),
                                'uploader': entry.get('uploader', 'Unknown Artist')
                            })
                return results
        return await asyncio.to_thread(_sc_search)


async def download_audio_by_id(video_id_or_url: str) -> tuple[str, str]:
    """Audio (MP3) yuklab olish va konvertatsiya qilish."""
    if video_id_or_url.startswith("http"):
        url = video_id_or_url
    else:
        url = f"https://www.youtube.com/watch?v={video_id_or_url}"
    
    ydl_opts = {
        **BASE_YDL_OPTS,
        'format': 'bestaudio/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Audio Track')
            file_id = info.get('id', 'audio')
            file_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp3")
            return file_path, title

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    """Video yuklab olish."""
    ydl_opts = {
        **BASE_YDL_OPTS,
        'format': 'best[ext=mp4]/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'max_filesize': 50 * 1024 * 1024,
    }

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return {
                "file_path": filename,
                "title": info.get("title", "Video"),
                "id": info.get("id")
            }

    return await asyncio.to_thread(_download)
    
