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

def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"

# ---------------------------------------------------------------------------
# QIDIRUV (SoundCloud & YouTube Fallback)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    return await asyncio.to_thread(_search_sync, query, limit)

def _search_sync(query: str, limit: int) -> list[dict]:
    # 1. SoundCloud orqali qidiruv
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
                    if entry and (entry.get('url') or entry.get('webpage_url')):
                        sc_url = entry.get('url') or entry.get('webpage_url')
                        items.append({
                            'id': sc_url,
                            'title': entry.get('title', 'Unknown Track'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader') or 'SoundCloud',
                        })
            if items:
                logging.info(f"✅ SoundCloud orqali {len(items)} ta qo'shiq topildi.")
                return items
    except Exception as e:
        logging.warning(f"SoundCloud qidiruvida xatolik: {e}")

    # 2. YouTube Search Fallback
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'user_agent': USER_AGENT,
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
                            'uploader': entry.get('uploader') or 'YouTube',
                        })
            if items:
                logging.info(f"✅ YouTube orqali {len(items)} ta qo'shiq topildi.")
                return items
    except Exception as e:
        logging.error(f"YouTube qidiruvida xatolik: {e}")

    return []

# ---------------------------------------------------------------------------
# AUDIO YUKLASH
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)
    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if track_id.startswith("http://") or track_id.startswith("https://"):
        target_url = track_id
        file_prefix = f"audio_{abs(hash(track_id))}"
    else:
        target_url = f"https://www.youtube.com/watch?v={track_id}"
        file_prefix = f"audio_{track_id}"

    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    # 1. COBALT API (aiohttp bilan)
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
                                    logging.info(f"✅ Cobalt API orqali muvaffaqiyatli yuklandi: {out_file}")
                                    return out_file, track_title or "Audio Track", None
    except Exception as e:
        logging.warning(f"Cobalt API yuklashda xatolik: {e}")

    # 2. SOUNDCLOUD / YT-DLP FALLBACK
    file_path, title = await asyncio.to_thread(_download_fallback_sync, target_url, file_prefix, track_title)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None

def _download_fallback_sync(target_url: str, file_prefix: str, track_title: str = None) -> tuple[str | None, str]:
    try:
        logging.info("🔄 Zaxira yo'li orqali yuklanmoqda...")
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
