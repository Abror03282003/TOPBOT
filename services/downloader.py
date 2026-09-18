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
# FFmpeg Sozlamalari
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
COOKIES_PATH = "cookies.txt"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.drgns.space",
    "https://vid.puffyan.us"
]

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.mha.fi",
    "https://pipedapi.drgns.space"
]

COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://cobalt.streamrip.net",
    "https://api.qewertyy.dev/cobalt"
]

def _ensure_cookies_file():
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if not cookies_env:
        return
    cleaned = cookies_env.replace("\\n", "\n").strip()
    try:
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(cleaned + "\n")
    except Exception as e:
        logging.error(f"Cookies xatosi: {e}")

def _has_cookies() -> bool:
    return os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0

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
    
    results = await _search_via_invidious(search_query, limit)
    if results:
        return results

    results = await _search_via_piped(search_query, limit)
    if results:
        return results

    def _yt_flat():
        opts = {
            'extract_flat': True,
            'skip_download': True,
            'ignoreerrors': True,
            'quiet': True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{search_query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry:
                        items.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Unknown'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader') or 'Unknown'
                        })
            return items
            
    return await asyncio.to_thread(_yt_flat)

async def _search_via_invidious(query: str, limit: int) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/search"
                params = {"q": query, "type": "video"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = []
                        for entry in data[:limit]:
                            if entry.get("videoId"):
                                results.append({
                                    'id': entry.get("videoId"),
                                    'title': entry.get("title", "Unknown"),
                                    'duration': format_duration(entry.get("lengthSeconds", 0)),
                                    'uploader': entry.get("author", "Unknown")
                                })
                        if results:
                            return results
            except Exception:
                continue
    return []

async def _search_via_piped(query: str, limit: int) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/search"
                params = {"q": query, "filter": "music_songs"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = []
                        for entry in data.get("items", [])[:limit]:
                            item_id = entry.get("url", "").replace("/watch?v=", "")
                            if item_id:
                                results.append({
                                    'id': item_id,
                                    'title': entry.get("title", "Unknown"),
                                    'duration': format_duration(entry.get("duration", 0)),
                                    'uploader': entry.get("uploaderName", "Unknown")
                                })
                        if results:
                            return results
            except Exception:
                continue
    return []

# ---------------------------------------------------------------------------
# AUDIO YUKLASH
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)

    cached_file_id = await get_cached_file(youtube_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if youtube_id.startswith("http"):
        url = youtube_id
        file_prefix = "url_" + str(abs(hash(youtube_id)))[-6:]
    else:
        url = f"https://www.youtube.com/watch?v={youtube_id}"
        file_prefix = youtube_id

    # 1. Direct yt-dlp (Ishonchli video formatidan ajratib olish)
    file_path, title = await asyncio.to_thread(_yt_dlp_download_audio, url, file_prefix)
    if file_path:
        return file_path, title, None

    # 2. Invidious Direct Audio Stream
    if not youtube_id.startswith("http"):
        inv_file, title = await _download_via_invidious(youtube_id, file_prefix)
        if inv_file:
            return inv_file, title, None

    # 3. Cobalt API
    cobalt_file = await _download_via_cobalt(url, file_prefix, is_audio=True)
    if cobalt_file:
        return cobalt_file, "Audio Track", None

    return None, "Audio Track", None

async def _download_via_invidious(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/videos/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    title = data.get("title", "Audio Track")
                    adaptive = data.get("adaptiveFormats", [])
                    
                    audio_streams = [f for f in adaptive if "audio" in f.get("type", "")]
                    if not audio_streams:
                        continue
                    
                    stream_url = audio_streams[0].get("url")
                    ext = audio_streams[0].get("container", "m4a")
                    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_inv.{ext}")

                    async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=40)) as s_resp:
                        if s_resp.status == 200:
                            with open(output_path, "wb") as f:
                                async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                logging.info("✅ Invidious stream orqali yuklandi.")
                                return output_path, title
            except Exception:
                continue
    return None, "Audio Track"

async def _download_via_cobalt(url: str, file_prefix: str, is_audio: bool = True) -> str | None:
    ext = "mp3" if is_audio else "mp4"
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_cobalt.{ext}")
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

    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in COBALT_INSTANCES:
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
                                        logging.info("✅ Cobalt API orqali yuklandi.")
                                        return output_path
            except Exception:
                continue
    return None

def _yt_dlp_download_audio(url: str, file_prefix: str) -> tuple[str | None, str]:
    _ensure_cookies_file()
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_raw.%(ext)s")
    
    # Video uchun 100% ishlayotgan format va player_client sozlamalari
    opts = {
        'format': 'bestvideo[ext=mp4][height<=360]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'user_agent': USER_AGENT,
        'extractor_args': {
            'youtube': {
                'player_client': ['tv_embedded', 'android_vr', 'web'],
            }
        }
    }

    if _has_cookies():
        opts['cookiefile'] = COOKIES_PATH

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Audio Track') if info else 'Audio Track'
            
            pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_raw.*")
            downloaded_files = glob.glob(pattern)
            
            for f in downloaded_files:
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    mp3_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")
                    
                    # FFmpeg orqali MP3 formatiga o'tkazamiz
                    if FFMPEG_PATH:
                        try:
                            sound = AudioSegment.from_file(f)
                            sound.export(mp3_path, format="mp3", bitrate="192k")
                            if os.path.exists(f):
                                os.remove(f)
                            logging.info(f"✅ Audio yuklandi va MP3ga o'tkazildi: {mp3_path}")
                            return mp3_path, title
                        except Exception as conv_err:
                            logging.error(f"FFmpeg konvertatsiya xatosi: {conv_err}")
                            return f, title
                    else:
                        logging.info(f"✅ Audio yuklandi: {f}")
                        return f, title
    except Exception as e:
        logging.error(f"yt-dlp audio xatoligi: {e}")

    return None, "Audio Track"

# ---------------------------------------------------------------------------
# MEDIA / VIDEO YUKLASH
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    return await asyncio.to_thread(_yt_dlp_download_video, url)

def _yt_dlp_download_video(url: str) -> dict:
    _ensure_cookies_file()
    file_prefix = "video_" + str(abs(hash(url)))[-6:]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_ytdlp.%(ext)s")

    opts = {
        'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
        'user_agent': USER_AGENT,
        'extractor_args': {
            'youtube': {
                'player_client': ['tv_embedded', 'android_vr', 'web'],
            }
        }
    }

    if _has_cookies():
        opts['cookiefile'] = COOKIES_PATH

    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH
        opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Video') if info else 'Video'
            video_id = info.get('id', file_prefix) if info else file_prefix

            pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_ytdlp.*")
            for f in glob.glob(pattern):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    logging.info(f"✅ Video yuklandi: {f}")
                    return {"file_path": f, "title": title, "id": video_id}
    except Exception as e:
        logging.error(f"Video yuklashda xatolik: {e}")

    return {"file_path": None, "title": "Video", "id": None}
