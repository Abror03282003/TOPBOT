import os
import glob
import shutil
import asyncio
import logging
import aiohttp
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file, save_to_cache

# ==========================================
# FFmpeg / FFprobe yo'llarini aniqlash
# ==========================================
FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or shutil.which("ffmpeg") or "/usr/bin/ffprobe"

if not (os.path.exists(FFMPEG_PATH) and os.path.exists(FFPROBE_PATH)):
    try:
        import imageio_ffmpeg
        imageio_bin = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(imageio_bin):
            FFMPEG_PATH = imageio_bin
            ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
            os.environ["PATH"] += os.pathsep + ffmpeg_dir
    except Exception as e:
        logging.warning(f"imageio_ffmpeg sozlash xatosi: {e}")

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    AudioSegment.converter = FFMPEG_PATH

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

INVIDIOUS_INSTANCES = [
    "https://invidious.flokinet.to",
    "https://invidious.privacydev.net",
    "https://invidious.drgns.space",
    "https://inv.nadeko.net",
]

def format_duration(seconds: int) -> str:
    """Saniyalarni daqiqa:soniya formatiga o'tkazish."""
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    """Invidious API orqali blokirovkasiz va tekor qidiruv."""
    async with aiohttp.ClientSession() as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/search"
                params = {"q": query, "type": "video"}
                async with session.get(url, params=params, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
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
                logging.warning(f"Qidiruvda Invidious instance xatosi ({instance}): {e}")
                continue

    # Agar Invidious ishlamasa zaxira yt-dlp qidiruvi
    return await _fallback_yt_dlp_search(query, limit)


async def _fallback_yt_dlp_search(query: str, limit: int) -> list[dict]:
    def _search():
        opts = {
            'quiet': True,
            'extract_flat': True,
            'skip_download': True,
            'nocheckcertificate': True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                results = []
                if res and 'entries' in res and res['entries']:
                    for entry in res['entries']:
                        if entry and entry.get('id'):
                            results.append({
                                'id': entry.get('id'),
                                'title': entry.get('title', 'Unknown Title'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader', 'Unknown Artist')
                            })
                return results
        except Exception as e:
            logging.error(f"yt-dlp search error: {e}")
            return []

    return await asyncio.to_thread(_search)


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    """
    Audio yuklab olish.
    1. Baza (kesh)
    2. Cobalt API
    3. Invidious API
    """
    youtube_id = str(video_id_or_url)

    # 1. Keshni tekshirish
    cached_file_id = await get_cached_file(youtube_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if str(video_id_or_url).startswith("http"):
        video_url = video_id_or_url
        file_prefix = "sc_" + str(abs(hash(video_id_or_url)))[-6:]
    else:
        video_url = f"https://www.youtube.com/watch?v={video_id_or_url}"
        file_prefix = youtube_id

    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    # 2. Cobalt API orqali yuklash
    async with aiohttp.ClientSession() as session:
        payload = {
            "url": video_url,
            "downloadMode": "audio",
            "audioFormat": "mp3"
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        try:
            async with session.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    audio_link = data.get("url")
                    if audio_link:
                        async with session.get(audio_link, timeout=30) as file_resp:
                            if file_resp.status == 200:
                                with open(output_path, "wb") as f:
                                    f.write(await file_resp.read())
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                    logging.info("✅ Audio Cobalt API orqali yuklandi.")
                                    return output_path, "Audio Track", None
        except Exception as e:
            logging.warning(f"Cobalt API xatosi: {e}")

    # 3. Invidious API orqali yuklash (Zaxira)
    fallback_file, fallback_title = await _download_via_invidious(youtube_id, file_prefix)
    if fallback_file and os.path.exists(fallback_file):
        return fallback_file, fallback_title, None

    return None, "Audio Track", None


async def _download_via_invidious(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    async with aiohttp.ClientSession() as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/videos/{video_id}"
                async with session.get(url, timeout=6, headers={"Accept": "application/json"}) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        title = data.get("title", "Audio Track")
                        adaptive_formats = data.get("adaptiveFormats", [])
                        audio_streams = [
                            f for f in adaptive_formats 
                            if f.get("container") in ["m4a", "webm", "mp3"] or "audio" in f.get("type", "")
                        ]

                        if audio_streams:
                            audio_url = audio_streams[0].get("url")
                            async with session.get(audio_url, timeout=25) as stream_resp:
                                if stream_resp.status == 200:
                                    with open(output_path, "wb") as f:
                                        f.write(await stream_resp.read())
                                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                        logging.info("✅ Audio Invidious orqali yuklandi.")
                                        return output_path, title
            except Exception:
                continue

    return None, "Audio Track"


async def download_media(url: str) -> dict:
    """Video yuklab olish (Cobalt API orqali)."""
    file_id = str(abs(hash(url)))[-8:]
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp4")

    async with aiohttp.ClientSession() as session:
        payload = {
            "url": url,
            "downloadMode": "auto"
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        try:
            async with session.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=12) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    media_link = data.get("url")
                    if media_link:
                        async with session.get(media_link, timeout=40) as file_resp:
                            if file_resp.status == 200:
                                with open(output_path, "wb") as f:
                                    f.write(await file_resp.read())
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                    return {
                                        "file_path": output_path,
                                        "title": "Downloaded Media",
                                        "id": file_id
                                    }
        except Exception as e:
            logging.error(f"Media download error: {e}")

    return {"file_path": None, "title": "Video", "id": None}
