import os
import shutil
import asyncio
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

if os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0:
    BASE_YDL_OPTS['cookiefile'] = COOKIES_PATH


def format_duration(seconds: int) -> str:
    """Saniyalarni MM:SS formatiga o'tkazadi."""
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


async def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """YouTube / YouTube Music orqali 10 ta aniq qo'shiqni qidiradi."""
    search_opts = {
        **BASE_YDL_OPTS,
        'extract_flat': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'],
                'player_skip': ['configs', 'webpage']
            }
        }
    }

    def _search():
        # Avval ytsearch bilan qidirib ko'radi
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            results = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry and entry.get('id'):
                        results.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Unknown Title'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader', 'Unknown Artist')
                        })
            return results

    try:
        if hasattr(asyncio, 'to_thread'):
            return await asyncio.to_thread(_search)
        else:
            return await asyncio.get_event_loop().run_in_executor(None, _search)
    except Exception as e:
        print(f"Search error: {e}")
        return []


async def download_audio_by_id(video_id: str) -> tuple[str, str]:
    """MP3 formatida yuklab olish."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    ydl_opts = {
        **BASE_YDL_OPTS,
        'format': 'bestaudio/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'mweb']
            }
        },
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

    if hasattr(asyncio, 'to_thread'):
        return await asyncio.to_thread(_download)
    else:
        return await asyncio.get_event_loop().run_in_executor(None, _download)


async def download_media(url: str) -> dict:
    """Instagram va YouTube videolarni yuklab olish."""
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

    if hasattr(asyncio, 'to_thread'):
        return await asyncio.to_thread(_download)
    else:
        return await asyncio.get_event_loop().run_in_executor(None, _download)
