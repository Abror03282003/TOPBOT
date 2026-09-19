import os
import glob
import shutil
import asyncio
import logging
import aiohttp
from pydub import AudioSegment
from database import get_cached_file, save_to_cache

__all__ = ["search_tracks", "download_audio_by_id", "download_media"]

# ---------------------------------------------------------------------------
# 1. FFmpeg va Yo'llar
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
# 2. QIDIRUV (Invidious Public API)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    search_query = query.strip()
    if not search_query:
        return []

    headers = {"User-Agent": USER_AGENT}
    # Barqaror Invidious va Piped qidiruv tugunlari
    nodes = [
        "https://inv.nadeko.net/api/v1/search",
        "https://invidious.nerdvpn.de/api/v1/search",
        "https://vyt.puzzle.is/api/v1/search"
    ]

    async with aiohttp.ClientSession(headers=headers) as session:
        for node in nodes:
            try:
                params = {"q": search_query, "type": "video"}
                async with session.get(node, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = []
                        for item in data[:limit]:
                            v_id = item.get("videoId")
                            if v_id:
                                items.append({
                                    'id': v_id,
                                    'title': item.get('title', 'Unknown Track'),
                                    'duration': format_duration(item.get('lengthSeconds', 0)),
                                    'uploader': item.get('author', 'YouTube')
                                })
                        if items:
                            return items
            except Exception:
                continue

    return []

# ---------------------------------------------------------------------------
# 3. AUDIO YUKLASH (Cobalt API Engine)
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)

    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if "watch?v=" in track_id or "youtu.be/" in track_id:
        v_id = track_id.split("v=")[-1].split("&")[0] if "v=" in track_id else track_id.split("/")[-1]
    else:
        v_id = track_id

    target_url = f"https://www.youtube.com/watch?v={v_id}"
    file_prefix = f"audio_{v_id}"

    # Cobalt API orqali yuklash (Railway IP taqiqlarini aylanib o'tadi)
    file_path, title = await _download_via_cobalt(target_url, file_prefix)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None

async def _download_via_cobalt(url: str, file_prefix: str) -> tuple[str | None, str]:
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
    out_mp3 = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    audio_url = data.get("url")
                    title = data.get("filename", "Audio Track").replace(".mp3", "")

                    if audio_url:
                        async with session.get(audio_url, timeout=aiohttp.ClientTimeout(total=60)) as file_resp:
                            if file_resp.status == 200:
                                with open(out_mp3, "wb") as f:
                                    async for chunk in file_resp.content.iter_chunked(64 * 1024):
                                        f.write(chunk)
                                if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 10240:
                                    logging.info(f"✅ Audio Cobalt orqali yuklandi: {out_mp3}")
                                    return out_mp3, title
    except Exception as e:
        logging.error(f"Cobalt yuklash xatosi: {e}")

    return None, "Audio Track"

# ---------------------------------------------------------------------------
# 4. MEDIA YUKLASH (Video)
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    out_mp4 = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")

    payload = {"url": url}
    headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    media_url = data.get("url")
                    if media_url:
                        async with session.get(media_url, timeout=aiohttp.ClientTimeout(total=90)) as file_resp:
                            if file_resp.status == 200:
                                with open(out_mp4, "wb") as f:
                                    async for chunk in file_resp.content.iter_chunked(64 * 1024):
                                        f.write(chunk)
                                if os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 10240:
                                    return {"file_path": out_mp4, "title": "Video", "id": file_prefix}
    except Exception as e:
        logging.error(f"Media yuklash xatosi: {e}")

    return {"file_path": None, "title": "Video", "id": None}
