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

# Ishchi va yangilangan Piped API instansiyalari
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.r34.app",
    "https://pipedapi.palvelintalo.fi",
    "https://pipedapi.drgns.space"
]

# Ishchi va yangilangan Invidious API instansiyalari
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.drgns.space"
]

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
# 2. QIDIRUV (Piped API / Invidious / Flat)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    search_query = query.strip()
    if not search_query:
        return []

    # 1. Piped API
    piped_res = await _piped_search(search_query, limit)
    if piped_res:
        return piped_res

    # 2. Invidious API
    inv_res = await _invidious_search(search_query, limit)
    if inv_res:
        return inv_res

    # 3. Zaxira: yt-dlp flat search
    return await asyncio.to_thread(_yt_flat_search, search_query, limit)

async def _piped_search(query: str, limit: int) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=4)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        for api_base in PIPED_INSTANCES:
            try:
                url = f"{api_base}/search"
                params = {"q": query, "filter": "music_songs"}
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = []
                        for item in data.get("items", [])[:limit]:
                            url_path = item.get("url", "")
                            v_id = url_path.split("v=")[-1] if "v=" in url_path else url_path.replace("/watch?v=", "")
                            if v_id:
                                items.append({
                                    'id': v_id,
                                    'title': item.get('title', 'Unknown Track'),
                                    'duration': format_duration(item.get('duration', 0)),
                                    'uploader': item.get('uploaderName', 'YouTube')
                                })
                        if items:
                            return items
            except Exception:
                continue
    return []

async def _invidious_search(query: str, limit: int) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=4)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        for api_base in INVIDIOUS_INSTANCES:
            try:
                url = f"{api_base}/api/v1/search"
                params = {"q": query, "type": "video"}
                async with session.get(url, params=params) as resp:
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

def _yt_flat_search(query: str, limit: int) -> list[dict]:
    opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'user_agent': USER_AGENT
    }
    try:
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
                            'uploader': entry.get('uploader') or 'YouTube'
                        })
            return items
    except Exception as e:
        logging.error(f"Flat qidiruv xatosi: {e}")
        return []

# ---------------------------------------------------------------------------
# 3. AUDIO YUKLASH (Piped Stream Direct Download)
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

    file_prefix = f"audio_{v_id}"

    # 1. Piped API orqali
    file_path, title = await _download_via_piped(v_id, file_prefix)
    if file_path:
        return file_path, title, None

    # 2. Invidious API orqali
    file_path, title = await _download_via_invidious(v_id, file_prefix)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None

async def _download_via_piped(v_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    out_mp3 = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    for api_base in PIPED_INSTANCES:
        try:
            url = f"{api_base}/streams/{v_id}"
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        title = data.get("title", "Audio Track")
                        audio_streams = data.get("audioStreams", [])

                        if audio_streams:
                            best_stream = max(audio_streams, key=lambda x: x.get("bitrate", 0))
                            stream_url = best_stream.get("url")

                            if stream_url:
                                async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=60)) as file_resp:
                                    if file_resp.status == 200:
                                        raw_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.tmp")
                                        with open(raw_file, "wb") as f:
                                            async for chunk in file_resp.content.iter_chunked(64 * 1024):
                                                f.write(chunk)

                                        if os.path.exists(raw_file) and os.path.getsize(raw_file) > 10240:
                                            if FFMPEG_PATH:
                                                try:
                                                    sound = AudioSegment.from_file(raw_file)
                                                    sound.export(out_mp3, format="mp3", bitrate="192k")
                                                    if os.path.exists(raw_file):
                                                        os.remove(raw_file)
                                                except Exception:
                                                    os.rename(raw_file, out_mp3)
                                            else:
                                                os.rename(raw_file, out_mp3)

                                            if os.path.exists(out_mp3):
                                                logging.info(f"✅ Audio Piped orqali yuklandi: {out_mp3}")
                                                return out_mp3, title
        except Exception as e:
            logging.warning(f"Piped API ({api_base}) xatosi: {e}")
            continue

    return None, "Audio Track"

async def _download_via_invidious(v_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    out_mp3 = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    for api_base in INVIDIOUS_INSTANCES:
        try:
            url = f"{api_base}/api/v1/videos/{v_id}"
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        title = data.get("title", "Audio Track")
                        adaptive = data.get("adaptiveFormats", [])
                        audio_streams = [f for f in adaptive if "audio" in f.get("type", "")]

                        if audio_streams:
                            stream_url = audio_streams[0].get("url")
                            if stream_url:
                                async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=60)) as file_resp:
                                    if file_resp.status == 200:
                                        raw_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_inv.tmp")
                                        with open(raw_file, "wb") as f:
                                            async for chunk in file_resp.content.iter_chunked(64 * 1024):
                                                f.write(chunk)

                                        if os.path.exists(raw_file) and os.path.getsize(raw_file) > 10240:
                                            if FFMPEG_PATH:
                                                try:
                                                    sound = AudioSegment.from_file(raw_file)
                                                    sound.export(out_mp3, format="mp3", bitrate="192k")
                                                    if os.path.exists(raw_file):
                                                        os.remove(raw_file)
                                                except Exception:
                                                    os.rename(raw_file, out_mp3)
                                            else:
                                                os.rename(raw_file, out_mp3)

                                            if os.path.exists(out_mp3):
                                                logging.info(f"✅ Audio Invidious orqali yuklandi: {out_mp3}")
                                                return out_mp3, title
        except Exception as e:
            logging.warning(f"Invidious API ({api_base}) xatosi: {e}")
            continue

    return None, "Audio Track"

# ---------------------------------------------------------------------------
# 4. MEDIA YUKLASH (Tuzatilgan asyncio syntax)
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    return await asyncio.to_thread(_download_social_video, url.strip())

def _download_social_video(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")

    opts = {
        'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
        'user_agent': USER_AGENT
    }

    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Video') if info else 'Video'
            video_id = info.get('id', file_prefix) if info else file_prefix

            pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
            for f in glob.glob(pattern):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    return {"file_path": f, "title": title, "id": video_id}
    except Exception as e:
        logging.error(f"Video yuklash xatosi: {e}")

    return {"file_path": None, "title": "Video", "id": None}
