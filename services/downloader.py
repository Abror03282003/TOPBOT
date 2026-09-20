import os
import glob
import shutil
import asyncio
import logging
import requests
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

def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"

# ---------------------------------------------------------------------------
# QIDIRUV (SoundCloud va YouTube muqobili)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    return await asyncio.to_thread(_search_sync, query, limit)

def _search_sync(query: str, limit: int) -> list[dict]:
    # 1-Bosqich: SoundCloud orqali qidirish (IP bloklanmaydi, juda tez ishlaydi)
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

    # 2-Bosqich: YouTube Search (Ochiq User-Agent bilan)
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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

    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    # 1. COBALT API ORQALI YUKLASH (Bulutli IP bloklarini chetlab o'tadi)
    try:
        logging.info(f"🚀 Cobalt API orqali yuklanmoqda: {target_url}")
        payload = {
            "url": target_url,
            "downloadMode": "audio",
            "audioFormat": "mp3"
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        response = requests.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=15)
        data = response.json()

        download_url = None
        if data.get("status") in ["tunnel", "redirect"]:
            download_url = data.get("url")

        if download_url:
            r = requests.get(download_url, stream=True, timeout=30)
            if r.status_code == 200:
                with open(out_file, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                    logging.info(f"✅ Cobalt API orqali muvaffaqiyatli yuklandi: {out_file}")
                    return out_file, track_title or "Audio Track"
    except Exception as e:
        logging.warning(f"Cobalt API yuklashda xatolik: {e}")

    # 2. SOUNDCLOUD / YT-DLP FALLBACK YUKLASH
    try:
        logging.info(f"🔄 Zaxira yo'li orqali yuklanmoqda...")
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
            title = info.get('title', 'Audio Track') if info else 'Audio Track'
            
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
    return await asyncio.to_thread(_download_video_sync, url.strip())

def _download_video_sync(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")
    
    try:
        payload = {"url": url, "downloadMode": "auto"}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        response = requests.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=15)
        data = response.json()
        
        if data.get("status") in ["tunnel", "redirect"]:
            v_url = data.get("url")
            r = requests.get(v_url, stream=True, timeout=60)
            v_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")
            with open(v_file, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            if os.path.exists(v_file) and os.path.getsize(v_file) > 10240:
                return {"file_path": v_file, "title": "Video", "id": file_prefix}
    except Exception as e:
        logging.error(f"Video yuklashda xatolik: {e}")

    return {"file_path": None, "title": "Video", "id": None}
