import os
import glob
import shutil
import asyncio
import logging
import aiohttp
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file, save_to_cache

# ---------------------------------------------------------------------------
# FFmpeg / FFprobe aniqlash va sozlash
# ---------------------------------------------------------------------------
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        logging.info(f"imageio_ffmpeg ishlatilmoqda: {FFMPEG_PATH}")
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
COOKIES_PATH = "cookies.txt"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'geo_bypass': True,
    'retries': 5,
    'fragment_retries': 5,
    'skip_unavailable_fragments': True,
    'sleep_interval': 1,
    'max_sleep_interval': 3,
    'socket_timeout': 20,
}

if FFMPEG_PATH:
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH

CLIENT_ATTEMPTS = [
    (['tv', 'tv_embedded'], True),
    (['android', 'mweb'], True),
    (['android_vr', 'web_creator'], True),
    (['ios', 'android'], False),
    (['mweb'], False),
    (None, False),
]

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.no-logs.how",
    "https://invidious.projectsegfau.lt"
]

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.mha.fi",
    "https://pipedapi.tokhmi.xyz"
]

COBALT_INSTANCES = [
    "https://cobalt.streamrip.net",
    "https://cobalt.qewertyy.dev",
    "https://api.cobalt.tools"
]

# ---------------------------------------------------------------------------
# Cookies va YDL Sozlamalar Boshqaruvi
# ---------------------------------------------------------------------------
def _ensure_cookies_file():
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if not cookies_env:
        return
    
    cleaned = cookies_env.replace("\\n", "\n").strip()
    
    if os.path.exists(COOKIES_PATH):
        try:
            with open(COOKIES_PATH, "r", encoding="utf-8") as f:
                if f.read().strip() == cleaned:
                    return
        except Exception:
            pass
    try:
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(cleaned + "\n")
    except Exception as e:
        logging.error(f"Cookies faylini yozishda xatolik: {e}")


def _has_cookies() -> bool:
    return os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0


def _build_opts(extra: dict, clients=None, use_cookies: bool = True) -> dict:
    _ensure_cookies_file()
    opts = {**BASE_YDL_OPTS, **extra}
    opts['user_agent'] = USER_AGENT

    if use_cookies and _has_cookies():
        opts['cookiefile'] = COOKIES_PATH
    else:
        opts.pop('cookiefile', None)

    extractor_args = {}
    if clients:
        extractor_args['player_client'] = list(clients)

    po_token = os.environ.get("YOUTUBE_PO_TOKEN")
    visitor_data = os.environ.get("YOUTUBE_VISITOR_DATA")
    if po_token:
        po_args = [f"web+{po_token}"]
        if visitor_data:
            po_args.append(visitor_data)
        extractor_args['po_token'] = po_args

    if extractor_args:
        opts['extractor_args'] = {'youtube': extractor_args}
    else:
        opts.pop('extractor_args', None)

    return opts


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"

# ---------------------------------------------------------------------------
# QIDIRUV (O'zgartirilmadi)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    search_query = query.strip()

    results = await _search_via_piped(search_query, limit, filter_type="music_songs")
    if results:
        return results

    results = await _search_via_piped(search_query, limit, filter_type="all")
    if results:
        return results

    results = await _search_via_invidious(search_query, limit)
    if results:
        return results

    def _yt_dlp_search():
        base = {
            'extract_flat': True,
            'skip_download': True,
            'ignoreerrors': True
        }
        for clients, use_cookies in CLIENT_ATTEMPTS:
            try:
                opts = _build_opts(base, clients, use_cookies)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    res = ydl.extract_info(f"ytsearch{limit}:{search_query}", download=False)
                results = []
                if res and res.get('entries'):
                    for entry in res['entries']:
                        if entry and entry.get('id'):
                            results.append({
                                'id': entry.get('id'),
                                'title': entry.get('title', 'Unknown Title'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader') or entry.get('channel') or 'Unknown Artist'
                            })
                if results:
                    return results
            except Exception as e:
                logging.warning(f"yt-dlp search error ({clients}): {e}")
        return []

    return await asyncio.to_thread(_yt_dlp_search)


async def _search_via_piped(query: str, limit: int, filter_type: str = "music_songs") -> list[dict]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/search"
                params = {"q": query, "filter": filter_type}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        items = data.get("items", [])
                        results = []
                        for entry in items[:limit]:
                            item_id = entry.get("url", "").replace("/watch?v=", "")
                            if item_id:
                                results.append({
                                    'id': item_id,
                                    'title': entry.get("title", "Unknown Title"),
                                    'duration': format_duration(entry.get("duration", 0)),
                                    'uploader': entry.get("uploaderName", "Unknown Artist")
                                })
                        if results:
                            return results
            except Exception:
                continue
    return []


async def _search_via_invidious(query: str, limit: int) -> list[dict]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/search"
                params = {"q": query, "type": "video"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        results = []
                        for entry in data[:limit]:
                            if entry.get("videoId"):
                                results.append({
                                    'id': entry.get("videoId"),
                                    'title': entry.get("title", "Unknown Title"),
                                    'duration': format_duration(entry.get("lengthSeconds", 0)),
                                    'uploader': entry.get("author", "Unknown Artist")
                                })
                        if results:
                            return results
            except Exception:
                continue
    return []

# ---------------------------------------------------------------------------
# AUDIO YUKLASH (YANGILANDI VA TUZATILDI)
# ---------------------------------------------------------------------------
def _find_downloaded(file_prefix: str) -> str | None:
    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}*")
    for f in glob.glob(pattern):
        if f.endswith(('.part', '.ytdl')):
            continue
        if os.path.exists(f) and os.path.getsize(f) > 10240: # Kamida 10KB
            return f
    return None


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)

    # 1. Kesh
    cached_file_id = await get_cached_file(youtube_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if youtube_id.startswith("http"):
        url = youtube_id
        file_prefix = "sc_" + str(abs(hash(youtube_id)))[-6:]
    else:
        url = f"https://www.youtube.com/watch?v={youtube_id}"
        file_prefix = youtube_id

    # 2. Piped API
    if not youtube_id.startswith("http"):
        file_path, title = await _download_via_piped(youtube_id, file_prefix)
        if file_path:
            return file_path, title, None

    # 3. Cobalt API
    cobalt_file = await _download_via_cobalt(url, file_prefix, is_audio=True)
    if cobalt_file:
        return cobalt_file, "Audio Track", None

    # 4. Invidious API
    if not youtube_id.startswith("http"):
        file_path, title = await _download_via_invidious(youtube_id, file_prefix)
        if file_path:
            return file_path, title, None

    # 5. yt-dlp (Zaxira)
    file_path, title = await asyncio.to_thread(_yt_dlp_download_audio, url, file_prefix)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None


async def _download_via_piped(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    title = data.get("title", "Audio Track")
                    audio_streams = data.get("audioStreams", [])
                    if not audio_streams:
                        continue
                    
                    stream = audio_streams[0]
                    audio_url = stream.get("url")
                    mime = stream.get("mimeType", "")
                    
                    # Asl audio formatiga qarab kengaytma beramiz
                    ext = "m4a" if "mp4" in mime or "m4a" in mime else "webm"
                    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_piped.{ext}")

                    async with session.get(audio_url, timeout=aiohttp.ClientTimeout(total=30)) as stream_resp:
                        if stream_resp.status == 200:
                            with open(output_path, "wb") as f:
                                async for chunk in stream_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                logging.info(f"✅ Piped API orqali yuklandi: {output_path}")
                                return output_path, title
            except Exception:
                continue

    return None, "Audio Track"


async def _download_via_cobalt(url: str, file_prefix: str, is_audio: bool = True) -> str | None:
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_cobalt.m4a")

    payload = {
        "url": url,
        "downloadMode": "audio",
        "audioFormat": "best"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in COBALT_INSTANCES:
            try:
                async with session.post(f"{instance}/", json=payload, timeout=aiohttp.ClientTimeout(total=7)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        media_link = data.get("url")
                        if media_link:
                            async with session.get(media_link, timeout=aiohttp.ClientTimeout(total=30)) as file_resp:
                                if file_resp.status == 200:
                                    with open(output_path, "wb") as f:
                                        async for chunk in file_resp.content.iter_chunked(64 * 1024):
                                            f.write(chunk)
                                    if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                        logging.info(f"✅ Cobalt API ({instance}) orqali yuklandi.")
                                        return output_path
            except Exception:
                continue

    return None


async def _download_via_invidious(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/videos/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    title = data.get("title", "Audio Track")
                    adaptive_formats = data.get("adaptiveFormats", [])
                    audio_streams = [
                        f for f in adaptive_formats
                        if "audio" in f.get("type", "") or f.get("container") in ["m4a", "webm", "mp3"]
                    ]
                    if not audio_streams:
                        continue
                    
                    stream = audio_streams[0]
                    audio_url = stream.get("url")
                    container = stream.get("container", "m4a")
                    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_inv.{container}")

                    async with session.get(audio_url, timeout=aiohttp.ClientTimeout(total=25)) as stream_resp:
                        if stream_resp.status == 200:
                            with open(output_path, "wb") as f:
                                async for chunk in stream_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                logging.info(f"✅ Invidious orqali yuklandi: {output_path}")
                                return output_path, title
            except Exception:
                continue

    return None, "Audio Track"


def _yt_dlp_download_audio(url: str, file_prefix: str) -> tuple[str | None, str]:
    title = "Audio Track"
    
    # Audio sifatini buzmasdan to'g'ridan-to'g'ri asl formatida (m4a, webm) yuklab olamiz
    extra = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_prefix}.%(ext)s'),
        'overwrites': True,
    }

    if FFMPEG_PATH:
        extra['ffmpeg_location'] = FFMPEG_PATH

    for clients, use_cookies in CLIENT_ATTEMPTS:
        opts = _build_opts(extra, clients, use_cookies)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    title = info.get('title', title)
            found = _find_downloaded(file_prefix)
            if found:
                logging.info(f"✅ yt-dlp audio yuklandi ({clients}): {found}")
                return found, title
        except Exception as e:
            logging.warning(f"yt-dlp audio error ({clients}): {e}")
            continue

    return None, title

# ---------------------------------------------------------------------------
# MEDIA YUKLASH (Video funksiyalaringiz o'zgarmasdan saqlandi)
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    file_prefix = "media_" + str(abs(hash(url)))[-6:]
    cobalt_file = await _download_via_cobalt(url, file_prefix, is_audio=False)
    if cobalt_file:
        return {"file_path": cobalt_file, "title": "Video", "id": file_prefix}

    return await asyncio.to_thread(_yt_dlp_download_media, url)


def _yt_dlp_download_media(url: str) -> dict:
    extra = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s.%(ext)s'),
        'max_filesize': 50 * 1024 * 1024,
        'overwrites': True,
    }
    if FFMPEG_PATH:
        extra['merge_output_format'] = 'mp4'

    for clients, use_cookies in CLIENT_ATTEMPTS:
        try:
            with yt_dlp.YoutubeDL(_build_opts(extra, clients, use_cookies)) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info or not isinstance(info, dict):
                    continue
                filename = ydl.prepare_filename(info)

            base, _ = os.path.splitext(filename)
            for ext in ('.mp4', '.mkv', '.webm'):
                if os.path.exists(base + ext) and os.path.getsize(base + ext) > 0:
                    filename = base + ext
                    break

            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                return {"file_path": filename, "title": info.get("title", "Video"), "id": info.get("id")}
        except Exception:
            continue

    return {"file_path": None, "title": "Video", "id": None}
