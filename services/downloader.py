import os
import glob
import shutil
import asyncio
import logging
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file

__all__ = ["search_tracks", "download_audio_by_id", "download_media"]

# FFmpeg va FFprobe ni aniqlash
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

if not FFPROBE_PATH and FFMPEG_PATH:
    candidate = os.path.join(os.path.dirname(FFMPEG_PATH), "ffprobe")
    FFPROBE_PATH = candidate if os.path.exists(candidate) else FFMPEG_PATH

if FFMPEG_PATH:
    AudioSegment.converter = FFMPEG_PATH
if FFPROBE_PATH:
    AudioSegment.ffprobe = FFPROBE_PATH

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIES_FILE = os.path.abspath("cookies.txt")

def update_cookies_file():
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if cookies_env:
        try:
            with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                f.write(cookies_env.strip() + "\n")
            logging.info("🍪 Cookies fayli muvaffaqiyatli saqlandi.")
        except Exception as e:
            logging.error(f"Cookies saqlashda xatolik: {e}")

# Ishga tushishida cookies.txt yaratish
update_cookies_file()

def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"

def _get_opts():
    update_cookies_file()
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    }
    if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 50:
        opts['cookiefile'] = COOKIES_FILE
    return opts

# ---------------------------------------------------------------------------
# QIDIRUV
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    return await asyncio.to_thread(_search_sync, query, limit)

def _search_sync(query: str, limit: int) -> list[dict]:
    # 1. YouTube Qidiruv
    try:
        opts = _get_opts()
        opts.update({
            'extract_flat': True,
            'skip_download': True,
            'extractor_args': {'youtube': {'player_client': ['web', 'mweb', 'android']}}
        })
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry and entry.get('id'):
                        title = entry.get('title', 'Unknown Track')
                        uploader = entry.get('uploader') or 'YouTube'
                        items.append({
                            'id': entry.get('id'),
                            'title': title,
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': uploader,
                        })
            if items:
                return items
    except Exception as e:
        logging.warning(f"YouTube qidiruv xatosi: {e}")

    # 2. SoundCloud Qidiruv (YouTube zaxirasi)
    try:
        opts = _get_opts()
        opts.update({'extract_flat': True, 'skip_download': True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry:
                        sc_url = entry.get('url') or entry.get('webpage_url')
                        if sc_url:
                            items.append({
                                'id': sc_url,
                                'title': entry.get('title', 'Unknown Track'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader') or 'SoundCloud'
                            })
            return items
    except Exception as e:
        logging.error(f"SoundCloud qidiruv xatosi: {e}")

    return []

# ---------------------------------------------------------------------------
# AUDIO YUKLASH
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)
    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    file_path, title = await asyncio.to_thread(_download_audio_sync, track_id, track_title)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None

def _download_audio_sync(track_id: str, track_title: str = None) -> tuple[str | None, str]:
    if track_id.startswith("http://") or track_id.startswith("https://"):
        target_url = track_id
        file_prefix = f"audio_{abs(hash(track_id))}"
    else:
        target_url = f"https://www.youtube.com/watch?v={track_id}"
        file_prefix = f"audio_{track_id}"

    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")

    # 1-Urinish: YouTube + Cookies
    clients = [['web'], ['mweb'], ['android'], ['ios']]
    for client in clients:
        try:
            opts = _get_opts()
            opts.update({
                'format': 'bestaudio/best',
                'outtmpl': outtmpl,
                'overwrites': True,
                'extractor_args': {'youtube': {'player_client': client, 'skip': ['hls', 'dash']}}
            })
            if FFMPEG_PATH:
                opts['ffmpeg_location'] = FFMPEG_PATH
                opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                title = info.get('title', 'Audio Track') if info else 'Audio Track'
                
                for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")):
                    if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                        logging.info(f"✅ YouTube ({client}) orqali yuklandi: {f}")
                        return f, title
        except Exception as e:
            logging.warning(f"YouTube client {client} xatosi: {e}")
            continue

    # 2-Urinish: SoundCloud Fallback (YouTube IP blok bo'lsa)
    try:
        search_target = target_url if target_url.startswith("http") else f"scsearch1:{track_title or track_id}"
        logging.info(f"🔄 SoundCloud orqali harakat qilinmoqda: {search_target}")

        opts = _get_opts()
        opts.update({
            'format': 'bestaudio/best',
            'outtmpl': outtmpl,
            'overwrites': True,
        })
        if FFMPEG_PATH:
            opts['ffmpeg_location'] = FFMPEG_PATH
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_target, download=True)
            title = "Audio Track"
            if info and 'entries' in info and info['entries']:
                title = info['entries'][0].get('title', 'Audio Track')
            elif info:
                title = info.get('title', 'Audio Track')

            for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    logging.info(f"✅ SoundCloud orqali yuklandi: {f}")
                    return f, title
    except Exception as sc_err:
        logging.error(f"SoundCloud fallback xatosi: {sc_err}")

    return None, "Audio Track"

# ---------------------------------------------------------------------------
# MEDIA YUKLASH (Video)
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    return await asyncio.to_thread(_download_video_sync, url.strip())

def _download_video_sync(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")
    
    opts = _get_opts()
    opts.update({
        'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'max_filesize': 50 * 1024 * 1024,
    })
    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Video') if info else 'Video'
            video_id = info.get('id', file_prefix) if info else file_prefix
            for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    return {"file_path": f, "title": title, "id": video_id}
    except Exception as e:
        logging.error(f"Video yuklash xatosi: {e}")

    return {"file_path": None, "title": "Video", "id": None}
