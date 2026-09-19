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

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# Railway IP blokidan holi bo'lgan va YouTube bazasini to'liq beradigan API instansiyalari
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.privacydev.net",
    "https://pipedapi.palvelu.org",
    "https://pipedapi.mha.fi"
]

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.flokinet.to",
    "https://invidious.privacydev.net"
]


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


# ---------------------------------------------------------------------------
# QIDIRUV (Piped va Invidious orqali YouTube bazasi bo'yicha)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 25) -> list[dict]:
    search_query = query.strip()

    # 1. Piped API (YouTube Music va Video qidiruvi)
    results = await _search_via_piped(search_query, limit)
    if results:
        return results

    # 2. Invidious API
    results = await _search_via_invidious(search_query, limit)
    if results:
        return results

    return []


async def _search_via_piped(query: str, limit: int) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/search"
                # filter bo'sh qoldirilsa ham qo'shiq, ham videolarni to'liq topadi
                params = {"q": query, "filter": "all"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = []
                        for entry in data.get("items", []):
                            if len(results) >= limit:
                                break
                            item_url = entry.get("url", "")
                            if "/watch?v=" in item_url:
                                item_id = item_url.split("/watch?v=")[1].split("&")[0]
                                results.append({
                                    'id': item_id,
                                    'title': entry.get("title", "Unknown"),
                                    'duration': format_duration(entry.get("duration", 0)),
                                    'uploader': entry.get("uploaderName", "YouTube")
                                })
                        if results:
                            return results
            except Exception:
                continue
    return []


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
                                    'uploader': entry.get("author", "YouTube")
                                })
                        if results:
                            return results
            except Exception:
                continue
    return []


# ---------------------------------------------------------------------------
# AUDIO YUKLASH (Railway Server-IP bloksiz)
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)

    # 1. Keshni tekshirish
    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if track_id.startswith("http"):
        file_prefix = "url_" + str(abs(hash(track_id)))[-6:]
        if "v=" in track_id:
            track_id = track_id.split("v=")[1].split("&")[0]
    else:
        file_prefix = track_id

    # 2. Piped Stream orqali yuklab olish (Bot check bo'lmaydi)
    piped_file, title = await _download_via_piped(track_id, file_prefix)
    if piped_file:
        return piped_file, title, None

    # 3. Invidious Stream orqali yuklab olish
    inv_file, inv_title = await _download_via_invidious(track_id, file_prefix)
    if inv_file:
        return inv_file, inv_title, None

    return None, "Audio Track", None


async def _download_via_piped(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    title = data.get("title", "Audio Track")
                    audio_streams = data.get("audioStreams", [])
                    if not audio_streams:
                        continue

                    # Oqim manzilini olamiz
                    stream_url = audio_streams[0].get("url")
                    ext = audio_streams[0].get("format", "m4a").lower()
                    raw_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_raw.{ext}")

                    async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=40)) as s_resp:
                        if s_resp.status == 200:
                            with open(raw_path, "wb") as f:
                                async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)

                            if os.path.exists(raw_path) and os.path.getsize(raw_path) > 10240:
                                mp3_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")
                                if FFMPEG_PATH:
                                    try:
                                        sound = AudioSegment.from_file(raw_path)
                                        sound.export(mp3_path, format="mp3", bitrate="192k")
                                        if os.path.exists(raw_path):
                                            os.remove(raw_path)
                                        return mp3_path, title
                                    except Exception:
                                        return raw_path, title
                                return raw_path, title
            except Exception:
                continue
    return None, "Audio Track"


async def _download_via_invidious(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/videos/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
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
                    raw_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_inv.{ext}")

                    async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=40)) as s_resp:
                        if s_resp.status == 200:
                            with open(raw_path, "wb") as f:
                                async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)

                            if os.path.exists(raw_path) and os.path.getsize(raw_path) > 10240:
                                mp3_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")
                                if FFMPEG_PATH:
                                    try:
                                        sound = AudioSegment.from_file(raw_path)
                                        sound.export(mp3_path, format="mp3", bitrate="192k")
                                        if os.path.exists(raw_path):
                                            os.remove(raw_path)
                                        return mp3_path, title
                                    except Exception:
                                        return raw_path, title
                                return raw_path, title
            except Exception:
                continue
    return None, "Audio Track"


# ---------------------------------------------------------------------------
# MEDIA / VIDEO YUKLASH
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-6:]
    if "v=" in url:
        v_id = url.split("v=")[1].split("&")[0]
        f_path, title = await _download_via_piped(v_id, file_prefix)
        if f_path:
            return {"file_path": f_path, "title": title, "id": v_id}
    return {"file_path": None, "title": "Video", "id": None}
