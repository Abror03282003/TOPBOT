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
# FFmpeg / FFprobe aniqlash
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
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'geo_bypass': True,
    'retries': 5,
    'socket_timeout': 30,
}

if FFMPEG_PATH:
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH

# Bot-guard bloklarini chetlab o'tish uchun kengaytirilgan mijozlar ro'yxati
CLIENT_ATTEMPTS = [
    (['tv', 'tv_embedded'], True),
    (['android_vr', 'web_creator'], True),
    (['ios', 'android'], False),
    (['mweb'], False),
    (None, False),
]

INVIDIOUS_INSTANCES = [
    "https://invidious.flokinet.to",
    "https://invidious.privacydev.net",
    "https://inv.nadeko.net",
    "https://invidious.drgns.space",
    "https://vid.puffyan.us"
]

PROXY_URL = os.environ.get("PROXY_URL")


def _ensure_cookies_file():
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if not cookies_env:
        return
    cleaned = cookies_env.strip()
    if os.path.exists(COOKIES_PATH):
        try:
            with open(COOKIES_PATH, "r", encoding="utf-8") as f:
                if f.read().strip() == cleaned:
                    return
        except Exception:
            pass
    try:
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(cleaned)
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
    
    if extractor_args:
        opts['extractor_args'] = {'youtube': extractor_args}
    else:
        opts.pop('extractor_args', None)

    if PROXY_URL:
        opts['proxy'] = PROXY_URL
    return opts


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


# ---------------------------------------------------------------------------
# QIDIRUV
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    search_query = query.strip()

    def _yt_dlp_search():
        base = {
            'extract_flat': True, 
            'skip_download': True, 
            'ignoreerrors': True
        }
        for clients, use_cookies in CLIENT_ATTEMPTS:
            try:
                with yt_dlp.YoutubeDL(_build_opts(base, clients, use_cookies)) as ydl:
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
                logging.warning(f"YouTube qidiruv ({clients}) xatosi: {e}")
        return []

    results = await asyncio.to_thread(_yt_dlp_search)
    if results:
        return results

    results = await _search_via_invidious(search_query, limit)
    if results:
        return results

    def _sc_search():
        base = {'extract_flat': True, 'skip_download': True, 'ignoreerrors': True}
        try:
            with yt_dlp.YoutubeDL(_build_opts(base, None, False)) as ydl:
                res = ydl.extract_info(f"scsearch{limit}:{search_query}", download=False)
            out = []
            if res and res.get('entries'):
                for entry in res['entries']:
                    if entry:
                        url_or_id = entry.get('url') or entry.get('webpage_url') or entry.get('id')
                        out.append({
                            'id': url_or_id,
                            'title': entry.get('title', 'Unknown Title'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader', 'Unknown Artist')
                        })
            return out
        except Exception as e:
            logging.error(f"SoundCloud search error: {e}")
            return []

    return await asyncio.to_thread(_sc_search)


async def _search_via_invidious(query: str, limit: int) -> list[dict]:
    try:
        async with aiohttp.ClientSession() as session:
            for instance in INVIDIOUS_INSTANCES:
                try:
                    url = f"{instance}/api/v1/search"
                    params = {"q": query, "type": "video"}
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=6)) as resp:
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
                except Exception as e:
                    logging.warning(f"Invidious qidiruv xatosi ({instance}): {e}")
                    continue
    except Exception as e:
        logging.warning(f"Invidious sessiyasi xatosi: {e}")
    return []


# ---------------------------------------------------------------------------
# AUDIO YUKLASH
# ---------------------------------------------------------------------------
def _find_downloaded(file_prefix: str) -> str | None:
    expected_mp3 = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")
    if os.path.exists(expected_mp3) and os.path.getsize(expected_mp3) > 0:
        return expected_mp3
    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
    for f in glob.glob(pattern):
        if f.endswith(('.part', '.ytdl')):
            continue
        if os.path.exists(f) and os.path.getsize(f) > 0:
            return f
    return None


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)

    cached_file_id = await get_cached_file(youtube_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if youtube_id.startswith("http"):
        url = youtube_id
        file_prefix = "sc_" + str(abs(hash(youtube_id)))[-6:]
    else:
        url = f"https://www.youtube.com/watch?v={youtube_id}"
        file_prefix = youtube_id

    # 1. yt-dlp (Asosiy)
    file_path, title = await asyncio.to_thread(_yt_dlp_download_audio, url, file_prefix)
    if file_path:
        return file_path, title, None

    # 2. Cobalt API (YT-DLP block bo'lganda birinchi API zaxirasi)
    cobalt_file = await _download_via_cobalt(url, file_prefix, is_audio=True)
    if cobalt_file:
        return cobalt_file, "Audio Track", None

    # 3. Invidious (So'nggi zaxira)
    if not youtube_id.startswith("http"):
        file_path, title = await _download_via_invidious(youtube_id, file_prefix)
        if file_path:
            return file_path, title, None

    return None, "Audio Track", None


def _yt_dlp_download_audio(url: str, file_prefix: str) -> tuple[str | None, str]:
    title = "Audio Track"
    
    formats_to_try = [
        'bestaudio/best',
        'ba/b',
        'worst'
    ]

    extra = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_prefix}.%(ext)s'),
        'overwrites': True,
    }
    
    if FFMPEG_PATH:
        extra['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    last_error = None
    for fmt in formats_to_try:
        extra['format'] = fmt
        for clients, use_cookies in CLIENT_ATTEMPTS:
            opts = _build_opts(extra, clients, use_cookies)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    title = info.get('title', title)
                found = _find_downloaded(file_prefix)
                if found:
                    logging.info(f"✅ yt-dlp orqali yuklandi ({clients}, cookies={use_cookies}): {found}")
                    return found, title
            except Exception as e:
                last_error = e
                logging.warning(f"yt-dlp urinish muvaffaqiyatsiz ({clients}, format={fmt}): {e}")
                continue

    logging.warning(f"yt-dlp orqali yuklab bo'lmadi. Oxirgi xato: {last_error}")
    return None, title


async def _download_via_invidious(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_inv.mp3")

    try:
        async with aiohttp.ClientSession() as session:
            for instance in INVIDIOUS_INSTANCES:
                try:
                    url = f"{instance}/api/v1/videos/{video_id}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=6),
                                            headers={"Accept": "application/json"}) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json(content_type=None)
                        title = data.get("title", "Audio Track")
                        adaptive_formats = data.get("adaptiveFormats", [])
                        audio_streams = [
                            f for f in adaptive_formats
                            if f.get("container") in ["m4a", "webm", "mp3"] or "audio" in f.get("type", "")
                        ]
                        if not audio_streams:
                            continue
                        audio_url = audio_streams[0].get("url")
                        async with session.get(audio_url, timeout=aiohttp.ClientTimeout(total=25)) as stream_resp:
                            if stream_resp.status == 200:
                                with open(output_path, "wb") as f:
                                    f.write(await stream_resp.read())
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                    logging.info("✅ Invidious orqali yuklandi.")
                                    return output_path, title
                except Exception as e:
                    logging.warning(f"Invidious yuklash xatosi ({instance}): {e}")
                    continue
    except Exception as e:
        logging.warning(f"Invidious sessiyasi xatosi: {e}")

    return None, "Audio Track"


# ---------------------------------------------------------------------------
# MEDIA YUKLASH
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
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
        except Exception as e:
            logging.warning(f"yt-dlp media urinish ({clients}) xatosi: {e}")
            continue

    return {"file_path": None, "title": "Video", "id": None}


async def _download_via_cobalt(url: str, file_prefix: str, is_audio: bool = True) -> str | None:
    ext = "mp3" if is_audio else "mp4"
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_cobalt.{ext}")

    async with aiohttp.ClientSession() as session:
        payload = {
            "url": url,
            "downloadMode": "audio" if is_audio else "auto",
            "audioFormat": "mp3"
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT
        }
        try:
            async with session.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    media_link = data.get("url")
                    if media_link:
                        async with session.get(media_link, timeout=aiohttp.ClientTimeout(total=35)) as file_resp:
                            if file_resp.status == 200:
                                with open(output_path, "wb") as f:
                                    f.write(await file_resp.read())
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                    logging.info(f"✅ Cobalt API orqali yuklandi: {output_path}")
                                    return output_path
        except Exception as e:
            logging.warning(f"Cobalt API xatosi: {e}")

    return None
