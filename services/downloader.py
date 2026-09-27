import os
import glob
import shutil
import asyncio
import logging
import aiohttp
from pydub import AudioSegment

FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or shutil.which("ffmpeg") or "/usr/bin/ffprobe"

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    AudioSegment.converter = FFMPEG_PATH
if FFPROBE_PATH and os.path.exists(FFPROBE_PATH):
    AudioSegment.ffprobe = FFPROBE_PATH

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# Faqat haqiqatda ishlayotgan API serverlar
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.privacydev.net"
]


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"


# ---------------------------------------------------------------------------
# QIDIRUV (Invidious API orqali - YouTube bloklariga tushmaydi)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []

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


# ---------------------------------------------------------------------------
# COBALT API (Rasmiy endpoint: api.cobalt.tools)
# ---------------------------------------------------------------------------
async def _download_via_cobalt(video_id: str) -> str | None:
    target_url = f"https://www.youtube.com/watch?v={video_id}" if not video_id.startswith("http") else video_id
    payload = {
        "url": target_url,
        "downloadMode": "audio",
        "audioFormat": "mp3",
        "audioBitrate": "192"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.post("https://api.cobalt.tools/api/json", json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    stream_url = data.get("url")
                    if stream_url:
                        output_path = os.path.join(DOWNLOAD_DIR, f"track_{video_id}.mp3")
                        async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=30)) as s_resp:
                            if s_resp.status == 200:
                                with open(output_path, "wb") as f:
                                    async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                        f.write(chunk)
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                    logging.info(f"✅ Cobalt orqali yuklandi: {output_path}")
                                    return output_path
        except Exception as e:
            logging.warning(f"Cobalt xatosi: {e}")

    return None


# ---------------------------------------------------------------------------
# INVIDIOUS DIRECT STREAM (Zaxira yuklovchi)
# ---------------------------------------------------------------------------
async def _download_via_invidious(video_id: str) -> str | None:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/videos/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    adaptive = data.get("adaptiveFormats", [])
                    audio_streams = [f for f in adaptive if "audio" in f.get("type", "")]
                    if not audio_streams:
                        continue

                    stream_url = audio_streams[0].get("url")
                    ext = audio_streams[0].get("container", "m4a")
                    raw_path = os.path.join(DOWNLOAD_DIR, f"{video_id}_raw.{ext}")

                    async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=30)) as s_resp:
                        if s_resp.status == 200:
                            with open(raw_path, "wb") as f:
                                async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)

                            if os.path.exists(raw_path) and os.path.getsize(raw_path) > 10240:
                                mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
                                if FFMPEG_PATH:
                                    try:
                                        sound = AudioSegment.from_file(raw_path)
                                        sound.export(mp3_path, format="mp3", bitrate="192k")
                                        if os.path.exists(raw_path):
                                            os.remove(raw_path)
                                        return mp3_path
                                    except Exception:
                                        return raw_path
                                return raw_path
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# AUDIO YUKLASH (KESH O'CHIRILGAN)
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None, *args, **kwargs) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)
    title_result = track_title or "Audio Track"

    # NOTE: Eski "lanati qo'shiq" qaytib chiqavermasligi uchun KESH (Database) tekshiruvi olib tashlandi!

    # 1. Cobalt API orqali yuklab olish
    cobalt_path = await _download_via_cobalt(youtube_id)
    if cobalt_path:
        return cobalt_path, title_result, None

    # 2. Invidious Stream orqali yuklab olish
    inv_path = await _download_via_invidious(youtube_id)
    if inv_path:
        return inv_path, title_result, None

    return None, title_result, None


async def download_media(url: str) -> dict:
    return {"file_path": None, "title": "Video", "id": None}
