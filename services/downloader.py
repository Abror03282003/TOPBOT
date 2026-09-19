import os
import glob
import shutil
import asyncio
import logging
import aiohttp
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file, save_to_cache

__all__ = ["search_tracks", "download_audio_by_id", "download_media"]

# ---------------------------------------------------------------------------
# 1. YouTube Cookies va Environment Sozlamasi
# ---------------------------------------------------------------------------
COOKIES_FILE = os.path.abspath("yt_cookies.txt")

def _prepare_cookies():
    raw_cookies = os.environ.get("YOUTUBE_COOKIES", "")
    if raw_cookies:
        try:
            cleaned = raw_cookies.replace("\\n", "\n").strip()
            with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                f.write(cleaned + "\n")
        except Exception as e:
            logging.error(f"Cookies yozishda xato: {e}")

_prepare_cookies()

# ---------------------------------------------------------------------------
# 2. FFmpeg Sozlamalari
# ---------------------------------------------------------------------------
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        logging.error(f"FFmpeg topilmadi: {e}")

if not FFPROBE_PATH and FFMPEG_PATH:
    candidate = os.path.join(os.path.dirname(FFMPEG_PATH), "ffprobe")
    FFPROBE_PATH = candidate if os.path.exists(candidate) else FFMPEG_PATH

if FFMPEG_PATH:
    AudioSegment.converter = FFMPEG_PATH
if FFPROBE_PATH:
    AudioSegment.ffprobe = FFPROBE_PATH

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# ---------------------------------------------------------------------------
# 3. Yordamchi Funksiyalar
# ---------------------------------------------------------------------------
def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        minutes = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{minutes}:{secs:02d}"
    except Exception:
        return "0:00"

# ---------------------------------------------------------------------------
# 4. QIDIRUV
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    search_query = query.strip()
    if not search_query:
        return []
    return await asyncio.to_thread(_yt_search, search_query, limit)

def _yt_search(query: str, limit: int) -> list[dict]:
    _prepare_cookies()
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'skip_download': True,
        'user_agent': USER_AGENT,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb'],
                'skip': ['hls', 'dash']
            }
        }
    }
    if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
        opts['cookiefile'] = COOKIES_FILE

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry and entry.get('id'):
                        items.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Unknown Track'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader') or entry.get('channel') or 'YouTube'
                        })
            if items:
                logging.info(f"✅ Qidiruv muvaffaqiyatli: '{query}' bo'yicha {len(items)} ta natija topildi.")
            return items
    except Exception as e:
        logging.error(f"Qidiruv xatoligi: {e}")
        return []

# ---------------------------------------------------------------------------
# 5. AUDIO YUKLASH (Fallback zanjiri bilan)
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)

    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if track_id.startswith("http"):
        file_prefix = "url_" + str(abs(hash(track_id)))[-6:]
        url = track_id
    else:
        file_prefix = track_id
        url = f"https://www.youtube.com/watch?v={track_id}"

    # 1. yt-dlp orqali turli player_client-lar bilan urinib ko'rish
    file_path, title = await asyncio.to_thread(_yt_download_audio, track_id, file_prefix)
    if file_path:
        return file_path, title, None

    # 2. Agar yt-dlp bloklansa, Cobalt API orqali yuklash
    cobalt_file = await _download_via_cobalt(url, file_prefix)
    if cobalt_file:
        return cobalt_file, "Audio Track", None

    return None, "Audio Track", None

def _yt_download_audio(video_id_or_url: str, file_prefix: str) -> tuple[str | None, str]:
    _prepare_cookies()
    url = f"https://www.youtube.com/watch?v={video_id_or_url}" if not video_id_or_url.startswith("http") else video_id_or_url
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")

    client_sets = [
        ['ios', 'android'],
        ['mweb', 'web_embedded'],
        ['tv_embedded', 'android_vr']
    ]

    for clients in client_sets:
        opts = {
            'format': 'ba/ba*/m4a/best',
            'outtmpl': outtmpl,
            'overwrites': True,
            'quiet': True,
            'no_warnings': True,
            'user_agent': USER_AGENT,
            'extractor_args': {
                'youtube': {
                    'player_client': clients,
                    'skip': ['hls', 'dash']
                }
            }
        }

        if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
            opts['cookiefile'] = COOKIES_FILE

        if FFMPEG_PATH:
            opts['ffmpeg_location'] = FFMPEG_PATH
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Audio Track') if info else 'Audio Track'

                pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
                for f in glob.glob(pattern):
                    if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                        logging.info(f"✅ Audio yuklandi ({clients}): {f}")
                        return f, title
        except Exception as e:
            logging.warning(f"yt-dlp client xatosi ({clients}): {e}")
            continue

    return None, "Audio Track"

async def _download_via_cobalt(url: str, file_prefix: str) -> str | None:
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_cobalt.mp3")
    payload = {
        "url": url,
        "downloadMode": "audio",
        "audioFormat": "mp3"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }

    instances = ["https://api.cobalt.tools", "https://cobalt.streamrip.net"]

    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in instances:
            try:
                async with session.post(f"{instance}/", json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        media_link = data.get("url")
                        if media_link:
                            async with session.get(media_link, timeout=aiohttp.ClientTimeout(total=40)) as file_resp:
                                if file_resp.status == 200:
                                    with open(output_path, "wb") as f:
                                        async for chunk in file_resp.content.iter_chunked(64 * 1024):
                                            f.write(chunk)
                                    if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                        logging.info("✅ Cobalt API orqali audio yuklandi.")
                                        return output_path
            except Exception as e:
                logging.warning(f"Cobalt xatosi: {e}")
                continue
    return None

# ---------------------------------------------------------------------------
# 6. VIDEO YUKLASH (Instagram, TikTok, YouTube Video va h.k)
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    return await asyncio.to_thread(_download_social_video, url.strip())

def _download_social_video(url: str) -> dict:
    _prepare_cookies()
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")

    opts = {
        'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
        'user_agent': USER_AGENT,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb']
            }
        }
    }

    if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
        opts['cookiefile'] = COOKIES_FILE

    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Video') if info else 'Video'
            video_id = info.get('id', file_prefix) if info else file_prefix

            pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
            for f in glob.glob(pattern):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    return {"file_path": f, "title": title, "id": video_id}
    except Exception as e:
        logging.error(f"Video yuklashda xatolik: {e}")

    return {"file_path": None, "title": "Video", "id": None}
