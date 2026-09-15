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

# Standart YDL sozlamalari
BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'impersonate': 'chrome',
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'android', 'mweb', 'tv'],
            'player_skip': ['configs', 'webpage']
        }
    }
}

if FFMPEG_PATH:
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH

if os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0:
    BASE_YDL_OPTS['cookiefile'] = COOKIES_PATH


async def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """
    Qo'shiq qidirish. YouTube blok bo'lgani uchun asosiy qidiruv SoundCloud
    orqali ishlaydi (u hech qachon IP blok va 'Not a bot' xatosini bermaydi).
    """
    # 1. Avval SoundCloud orqali qidiramiz
    sc_opts = {
        **BASE_YDL_OPTS,
        'extract_flat': True,
        'default_search': f'scsearch{limit}',
    }
    
    def _search_soundcloud():
        with yt_dlp.YoutubeDL(sc_opts) as ydl:
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

    try:
        results = await asyncio.to_thread(_search_soundcloud)
        if results:
            return results
    except Exception as e:
        print(f"SoundCloud qidiruv xatosi: {e}")

    # 2. Agar SoundCloud natija bermasa, YouTube'ni sinab ko'ramiz
    yt_opts = {
        **BASE_YDL_OPTS,
        'extract_flat': True,
        'default_search': f'ytsearch{limit}',
    }

    def _search_youtube():
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
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

    return await asyncio.to_thread(_search_youtube)


async def download_audio_by_id(video_id_or_url: str) -> tuple[str, str]:
    """Audio (MP3) yuklab olish."""
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

    try:
        return await asyncio.to_thread(_download)
    except Exception as e:
        # Agar YouTube bloklasa, SoundCloud'dan topib yuklaydi
        if "http" not in video_id_or_url:
            def _fallback_sc_download():
                sc_opts = {
                    **BASE_YDL_OPTS,
                    'format': 'bestaudio/best',
                    'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                }
                with yt_dlp.YoutubeDL(sc_opts) as ydl:
                    info = ydl.extract_info(f"scsearch1:{video_id_or_url}", download=True)
                    if info and 'entries' in info and info['entries']:
                        entry = info['entries'][0]
                        title = entry.get('title', 'Audio Track')
                        file_id = entry.get('id', 'audio')
                        file_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp3")
                        return file_path, title
                    raise e
            return await asyncio.to_thread(_fallback_sc_download)
        raise e


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
