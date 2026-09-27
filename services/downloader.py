import os
import glob
import shutil
import asyncio
import logging
import uuid
import aiohttp
import yt_dlp
from database import get_cached_file

__all__ = ["search_tracks", "download_audio_by_id", "download_media"]

logging.basicConfig(level=logging.INFO)

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FFMPEG_PATH = shutil.which("ffmpeg")
if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG_PATH = None

COOKIES_FILE = os.path.join(DOWNLOAD_DIR, "cookies.txt")
raw_cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()

if raw_cookies:
    try:
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            f.write(raw_cookies)
        logging.info("✅ YouTube cookies.txt fayli yaratildi.")
    except Exception as e:
        logging.error(f"Cookies yozishda xatolik: {e}")
        COOKIES_FILE = None
else:
    COOKIES_FILE = None

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

PIPED_INSTANCES = [
    "https://pipedapi.mha.fi",
    "https://piped-api.garudalinux.org",
    "https://pipedapi.lunar.icu",
    "https://pipedapi.smnz.de"
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
# QIDIRUV FUNKSIYALARI
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []

    results = await asyncio.to_thread(_search_ytdlp_sync, query, limit)
    if results:
        return results

    return await asyncio.to_thread(_search_soundcloud_sync, query, limit)


def _search_ytdlp_sync(query: str, limit: int) -> list[dict]:
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'extractor_args': {'youtube': {'player_client': ['tv', 'android']}}
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
                return items
    except Exception:
        pass
    return []

# ---------------------------------------------------------------------------
# AUDIO YUKLASH FUNKSIYALARI
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)

    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, track_title or "Audio Track", cached_file_id

    # Har doim unikal fayl nomi berish (eski fayllar chalkashmasligi uchun)
    unique_hash = uuid.uuid4().hex[:10]
    file_prefix = f"audio_{unique_hash}"
    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    if not track_id.startswith("http://") and not track_id.startswith("https://"):
        target_url = f"https://www.youtube.com/watch?v={track_id}"
        video_id = track_id
    else:
        target_url = track_id
        video_id = track_id.split("v=")[-1].split("&")[0] if "v=" in track_id else None

    # 1. Piped API orqali yuklash urinishi (agar YouTube ID bo'lsa)
    if video_id:
        file_path = await _download_via_piped(video_id, out_file)
        if file_path:
            return file_path, track_title or "Audio Track", None

    # 2. yt-dlp orqali to'g'ridan-to'g'ri yuklash urinishi
    file_path, title = await asyncio.to_thread(_download_ytdlp_sync, target_url, file_prefix, track_title)
    if file_path:
        return file_path, title, None

    # 3. ZAXIRA (FALLBACK): YouTube IP bloklagan bo'lsa, SoundCloud orqali qidirib yuklash
    search_query = track_title if track_title else target_url
    logging.info(f"⚠️ YouTube yuklay olmadi. SoundCloud orqali zaxira yuklash boshlandi: {search_query}")
    file_path, sc_title = await asyncio.to_thread(_download_soundcloud_fallback_sync, search_query, file_prefix)
    if file_path:
        return file_path, sc_title or track_title or "Audio Track", None

    return None, track_title or "Audio Track", None


async def _download_via_piped(video_id: str, out_file: str) -> str | None:
    for instance in PIPED_INSTANCES:
        try:
            api_url = f"{instance}/streams/{video_id}"
            async with get_session() as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        audio_streams = data.get("audioStreams", [])
                        if audio_streams:
                            best_audio = max(audio_streams, key=lambda x: int(x.get("bitrate", 0)))
                            download_url = best_audio.get("url")
                            if download_url:
                                async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=25)) as file_resp:
                                    if file_resp.status == 200:
                                        with open(out_file, 'wb') as f:
                                            async for chunk in file_resp.content.iter_chunked(16384):
                                                f.write(chunk)
                                        if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                                            return out_file
        except Exception:
            continue
    return None


def _download_ytdlp_sync(target_url: str, file_prefix: str, track_title: str = None) -> tuple[str | None, str]:
    try:
        opts = {
            'format': 'ba/b',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
            'overwrites': True,
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': {'player_client': ['tv', 'android']}},
            'http_headers': {'User-Agent': USER_AGENT}
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
        logging.error(f"yt-dlp yuklashda IP/sotib olish xatosi: {e}")

    return None, track_title or "Audio Track"


def _download_soundcloud_fallback_sync(query: str, file_prefix: str) -> tuple[str | None, str | None]:
    try:
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
            'quiet': True,
            'no_warnings': True,
        }

        if FFMPEG_PATH:
            opts['ffmpeg_location'] = FFMPEG_PATH
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        search_target = query if query.startswith("http") else f"scsearch1:{query}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_target, download=True)
            title = None
            if info:
                if 'entries' in info and len(info['entries']) > 0:
                    title = info['entries'][0].get('title')
                else:
                    title = info.get('title')

            for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    return f, title
    except Exception as e:
        logging.error(f"SoundCloud fallback xatosi: {e}")

    return None, None

# ---------------------------------------------------------------------------
# MEDIA YUKLASH FUNKSIYASI
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    url = url.strip()
    return await asyncio.to_thread(_download_media_sync, url)

def _download_media_sync(url: str) -> dict:
    unique_hash = uuid.uuid4().hex[:8]
    file_prefix = f"video_{unique_hash}"
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")

    opts = {
        'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
        'user_agent': USER_AGENT
    }

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
        logging.error(f"Video yuklash xatosi: {e}")

    return {"file_path": None, "title": "Video", "id": None}
