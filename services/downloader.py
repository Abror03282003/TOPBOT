import os
import glob
import shutil
import asyncio
import logging
import aiohttp
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file

__all__ = ["search_tracks", "download_audio_by_id", "download_media"]

logging.basicConfig(level=logging.INFO)

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

COOKIES_FILE = os.path.join(DOWNLOAD_DIR, "cookies.txt")
raw_cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()

if raw_cookies:
    try:
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            f.write(raw_cookies)
        logging.info("✅ YouTube cookies.txt fayli yaratildi.")
    except Exception as e:
        logging.error(f"Cookies faylini yozishda xatolik: {e}")
        COOKIES_FILE = None
else:
    COOKIES_FILE = None

USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"

# Barqaror Cobalt hamda Proxy manbalari
COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://cobalt.qtfy.eu",
    "https://cobalt.vxo.im"
]

def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"

def get_session():
    connector = aiohttp.TCPConnector(ssl=False)
    return aiohttp.ClientSession(connector=connector, headers={"User-Agent": USER_AGENT})

# ---------------------------------------------------------------------------
# QIDIRUV
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []

    # 1. yt-dlp flat qidiruv
    results = await asyncio.to_thread(_search_ytdlp_sync, query, limit)
    if results:
        return results

    # 2. SoundCloud zaxira qidiruvi (YouTube IP bloklangan hollarda)
    return await asyncio.to_thread(_search_soundcloud_sync, query, limit)


def _search_ytdlp_sync(query: str, limit: int) -> list[dict]:
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'mweb'],
                }
            }
        }
        if COOKIES_FILE and os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
            opts['cookiefile'] = COOKIES_FILE

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
                logging.info(f"✅ yt-dlp orqali {len(items)} ta qo'shiq topildi.")
                return items
    except Exception as e:
        logging.warning(f"yt-dlp search xatosi: {e}")
    return []


def _search_soundcloud_sync(query: str, limit: int) -> list[dict]:
    try:
        opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    webpage_url = entry.get('webpage_url') or entry.get('url')
                    if webpage_url:
                        items.append({
                            'id': webpage_url,
                            'title': entry.get('title', 'Unknown Track'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader') or 'SoundCloud',
                        })
            if items:
                logging.info(f"✅ SoundCloud orqali {len(items)} ta qo'shiq topildi.")
                return items
    except Exception:
        pass
    return []

# ---------------------------------------------------------------------------
# YUKLASH
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)
    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if not track_id.startswith("http://") and not track_id.startswith("https://"):
        target_url = f"https://www.youtube.com/watch?v={track_id}"
        file_prefix = f"audio_{track_id}"
    else:
        target_url = track_id
        file_prefix = f"audio_{abs(hash(track_id))}"

    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    # 1. Cobalt API
    logging.info(f"🚀 Cobalt API orqali yuklanmoqda: {target_url}")
    file_path = await _download_via_cobalt(target_url, out_file)
    if file_path:
        return file_path, track_title or "Audio Track", None

    # 2. YT-DLP (iOS / Web Clients)
    logging.info(f"🚀 yt-dlp client orqali yuklanmoqda: {target_url}")
    file_path, title = await asyncio.to_thread(_download_ytdlp_client_sync, target_url, file_prefix, track_title)
    if file_path:
        return file_path, title, None

    # 3. SoundCloud fallback (agar target_url SoundCloud bo'lsa)
    if "soundcloud.com" in target_url:
        file_path, title = await asyncio.to_thread(_download_soundcloud_sync, target_url, file_prefix, track_title)
        if file_path:
            return file_path, title, None

    return None, "Audio Track", None


async def _download_via_cobalt(target_url: str, out_file: str) -> str | None:
    payload = {"url": target_url, "downloadMode": "audio", "audioFormat": "mp3"}
    headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT}
    
    for instance in COBALT_INSTANCES:
        try:
            async with get_session() as session:
                async with session.post(instance, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        download_url = data.get("url")
                        if download_url:
                            async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=30)) as file_resp:
                                if file_resp.status == 200:
                                    with open(out_file, 'wb') as f:
                                        async for chunk in file_resp.content.iter_chunked(16384):
                                            f.write(chunk)
                                    if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                                        logging.info("✅ Cobalt API orqali muvaffaqiyatli yuklandi.")
                                        return out_file
        except Exception:
            continue
    return None


def _download_ytdlp_client_sync(target_url: str, file_prefix: str, track_title: str = None) -> tuple[str | None, str]:
    try:
        opts = {
            'format': 'ba/b',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
            'overwrites': True,
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'mweb', 'tv'],
                    'player_skip': ['webpage', 'configs'],
                }
            },
            'http_headers': {
                'User-Agent': 'com.google.ios.youtube/19.14.3 (iPhone14,3; U; CPU iOS 15_6 like Mac OS X; en_US)',
            }
        }

        if COOKIES_FILE and os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
            opts['cookiefile'] = COOKIES_FILE

        if FFMPEG_PATH:
            opts['ffmpeg_location'] = FFMPEG_PATH
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            title = info.get('title', track_title or 'Audio Track') if info else 'Audio Track'
            
            for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    return f, title
    except Exception as e:
        logging.error(f"yt-dlp yuklash xatosi: {e}")

    return None, "Audio Track"


def _download_soundcloud_sync(target_url: str, file_prefix: str, track_title: str = None) -> tuple[str | None, str]:
    try:
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
            'quiet': True,
        }
        if FFMPEG_PATH:
            opts['ffmpeg_location'] = FFMPEG_PATH
            opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            title = info.get('title', track_title or 'Audio Track') if info else 'Audio Track'
            for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    return f, title
    except Exception:
        pass
    return None, "Audio Track"


async def download_media(url: str) -> dict:
    url = url.strip()
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    v_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")

    for instance in COBALT_INSTANCES:
        try:
            payload = {"url": url, "downloadMode": "auto"}
            headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT}
            async with get_session() as session:
                async with session.post(instance, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        v_url = data.get("url")
                        if v_url:
                            async with session.get(v_url, timeout=aiohttp.ClientTimeout(total=60)) as file_resp:
                                if file_resp.status == 200:
                                    with open(v_file, 'wb') as f:
                                        async for chunk in file_resp.content.iter_chunked(8192):
                                            f.write(chunk)
                                    if os.path.exists(v_file) and os.path.getsize(v_file) > 10240:
                                        return {"file_path": v_file, "title": "Video", "id": file_prefix}
        except Exception:
            continue

    return {"file_path": None, "title": "Video", "id": None}
