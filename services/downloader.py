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

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.drgns.space",
    "https://vid.puffyan.us"
]

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.privacydev.net"
]

def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"

# ---------------------------------------------------------------------------
# KO'P BOSQICHLI SERGAK QIDIRUV
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []

    # 1. YouTube Web Search (yt-dlp mweb client - eng ko'p natija beradi)
    results = await asyncio.to_thread(_search_ytdlp_sync, query, limit)
    if results:
        return results

    # 2. Piped API orqali qidiruv
    results = await _search_piped(query, limit)
    if results:
        return results

    # 3. Invidious API orqali qidiruv
    results = await _search_invidious(query, limit)
    if results:
        return results

    # 4. SoundCloud Fallback
    return await asyncio.to_thread(_search_soundcloud_sync, query, limit)


def _search_ytdlp_sync(query: str, limit: int) -> list[dict]:
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'user_agent': USER_AGENT,
            'extractor_args': {
                'youtube': {
                    'player_client': ['mweb', 'android']
                }
            }
        }
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
                logging.info(f"✅ yt-dlp mweb orqali {len(items)} ta qo'shiq topildi.")
                return items
    except Exception as e:
        logging.warning(f"yt-dlp search xatosi: {e}")
    return []


async def _search_piped(query: str, limit: int) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/search"
                params = {"q": query, "filter": "music_songs"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = []
                        for entry in data.get("items", [])[:limit]:
                            v_id = entry.get("url", "").replace("/watch?v=", "")
                            if v_id:
                                items.append({
                                    'id': v_id,
                                    'title': entry.get("title", "Unknown Track"),
                                    'duration': format_duration(entry.get("duration", 0)),
                                    'uploader': entry.get("uploaderName", "YouTube")
                                })
                        if items:
                            logging.info(f"✅ Piped orqali {len(items)} ta qo'shiq topildi.")
                            return items
            except Exception:
                continue
    return []


async def _search_invidious(query: str, limit: int) -> list[dict]:
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/search"
                params = {"q": query, "type": "video"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = []
                        for entry in data[:limit]:
                            if entry.get("videoId"):
                                items.append({
                                    'id': entry.get("videoId"),
                                    'title': entry.get("title", "Unknown Track"),
                                    'duration': format_duration(entry.get("lengthSeconds", 0)),
                                    'uploader': entry.get("author", "YouTube")
                                })
                        if items:
                            logging.info(f"✅ Invidious orqali {len(items)} ta qo'shiq topildi.")
                            return items
            except Exception:
                continue
    return []


def _search_soundcloud_sync(query: str, limit: int) -> list[dict]:
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    webpage_url = entry.get('webpage_url') or entry.get('url')
                    if webpage_url and "soundcloud.com/" in webpage_url and "api.soundcloud.com" not in webpage_url:
                        items.append({
                            'id': webpage_url,
                            'title': entry.get('title', 'Unknown Track'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader') or 'SoundCloud',
                        })
            if items:
                logging.info(f"✅ SoundCloud orqali {len(items)} ta qo'shiq topildi.")
                return items
    except Exception as e:
        logging.warning(f"SoundCloud qidiruv xatosi: {e}")
    return []

# ---------------------------------------------------------------------------
# AUDIO YUKLASH
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)
    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if not track_id.startswith("http://") and not track_id.startswith("https://"):
        file_path, title = await _download_via_invidious_stream(track_id, track_title)
        if file_path:
            return file_path, title, None
        target_url = f"https://www.youtube.com/watch?v={track_id}"
        file_prefix = f"audio_{track_id}"
    else:
        target_url = track_id
        file_prefix = f"audio_{abs(hash(track_id))}"

    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    try:
        logging.info(f"🚀 Cobalt API orqali yuklanmoqda: {target_url}")
        payload = {
            "url": target_url,
            "downloadMode": "audio",
            "audioFormat": "mp3"
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post("https://api.cobalt.tools/", json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    download_url = data.get("url") if data.get("status") in ["tunnel", "redirect"] else None
                    if download_url:
                        async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=40)) as file_resp:
                            if file_resp.status == 200:
                                with open(out_file, 'wb') as f:
                                    async for chunk in file_resp.content.iter_chunked(8192):
                                        f.write(chunk)
                                if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                                    logging.info(f"✅ Cobalt API orqali yuklandi: {out_file}")
                                    return out_file, track_title or "Audio Track", None
    except Exception as e:
        logging.warning(f"Cobalt API xatosi: {e}")

    file_path, title = await asyncio.to_thread(_download_fallback_sync, target_url, file_prefix, track_title)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None


async def _download_via_invidious_stream(video_id: str, track_title: str = None) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/videos/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        title = data.get("title", track_title or "Audio Track")
                        adaptive = data.get("adaptiveFormats", [])
                        audio_streams = [f for f in adaptive if "audio" in f.get("type", "")]
                        
                        if audio_streams:
                            audio_url = audio_streams[0].get("url")
                            ext = audio_streams[0].get("container", "m4a")
                            raw_file = os.path.join(DOWNLOAD_DIR, f"inv_{video_id}.{ext}")

                            async with session.get(audio_url, timeout=aiohttp.ClientTimeout(total=30)) as s_resp:
                                if s_resp.status == 200:
                                    with open(raw_file, "wb") as f:
                                        async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                            f.write(chunk)

                                    if os.path.exists(raw_file) and os.path.getsize(raw_file) > 10240:
                                        mp3_file = os.path.join(DOWNLOAD_DIR, f"inv_{video_id}.mp3")
                                        if FFMPEG_PATH:
                                            try:
                                                sound = AudioSegment.from_file(raw_file)
                                                sound.export(mp3_file, format="mp3", bitrate="192k")
                                                os.remove(raw_file)
                                                return mp3_file, title
                                            except Exception:
                                                return raw_file, title
                                        return raw_file, title
            except Exception:
                continue
    return None, track_title or "Audio Track"


def _download_fallback_sync(target_url: str, file_prefix: str, track_title: str = None) -> tuple[str | None, str]:
    try:
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
            'overwrites': True,
            'quiet': True,
        }
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
        logging.error(f"Zaxira yuklashda xatolik: {e}")

    return None, "Audio Track"

# ---------------------------------------------------------------------------
# MEDIA YUKLASH (Video)
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    url = url.strip()
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    v_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")

    try:
        payload = {"url": url, "downloadMode": "auto"}
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post("https://api.cobalt.tools/", json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    if data.get("status") in ["tunnel", "redirect"]:
                        v_url = data.get("url")
                        async with session.get(v_url, timeout=aiohttp.ClientTimeout(total=60)) as file_resp:
                            if file_resp.status == 200:
                                with open(v_file, 'wb') as f:
                                    async for chunk in file_resp.content.iter_chunked(8192):
                                        f.write(chunk)
                                if os.path.exists(v_file) and os.path.getsize(v_file) > 10240:
                                    return {"file_path": v_file, "title": "Video", "id": file_prefix}
    except Exception as e:
        logging.error(f"Video yuklashda xatolik: {e}")

    return {"file_path": None, "title": "Video", "id": None}
