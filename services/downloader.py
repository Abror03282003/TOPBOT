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

# Piped API namunalari (ochiq proksi serverlar)
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.yt",
    "https://pipedapi.mha.fi",
    "https://piped-api.garudalinux.org"
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
# 2. QIDIRUV (Piped API / Flat Search)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    search_query = query.strip()
    if not search_query:
        return []

    # 1. Piped API orqali qidirish (YouTube ma'lumotlarini tez va taqiqsiz beradi)
    piped_res = await _piped_search(search_query, limit)
    if piped_res:
        return piped_res

    # 2. Zaxira: yt-dlp flat search
    return await asyncio.to_thread(_yt_flat_search, search_query, limit)

async def _piped_search(query: str, limit: int) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    for api_base in PIPED_INSTANCES:
        try:
            url = f"{api_base}/search?q={query}&filter=music_songs"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
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

    # 1. Piped API orqali audio oqimini to'g'ridan-to'g'ri olish
    file_path, title = await _download_via_piped(v_id, file_prefix)
    if file_path:
        return file_path, title, None

    # 2. Zaxira: Cobalt API
    file_path, title = await _download_via_cobalt(f"https://www.youtube.com/watch?v={v_id}", file_prefix)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None

async def _download_via_piped(v_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    out_mp3 = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    for api_base in PIPED_INSTANCES:
        try:
            url = f"{api_base}/streams/{v_id}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=7)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        title = data.get("title", "Audio Track")
                        audio_streams = data.get("audioStreams", [])

                        if audio_streams:
                            # Eng sifatli audio oqimini tanlash
                            best_stream = max(audio_streams, key=lambda x: x.get("bitrate", 0))
                            stream_url = best_stream.get("url")

                            if stream_url:
                                async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=90)) as file_resp:
                                    if file_resp.status == 200:
                                        raw_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.tmp")
                                        with open(raw_file, "wb") as f:
                                            async for chunk in file_resp.content.iter_chunked(64 * 1024):
                                                f.write(chunk)

                                        # FFmpeg orqali toza MP3 ga o'tkazish
                                        if os.path.exists(raw_file) and os.path.getsize(raw_file) > 10240:
                                            if FFMPEG_PATH:
                                                cmd = f'"{FFMPEG_PATH}" -y -i "{raw_file}" -vn -ar 44100 -ac 2 -b:a 192k "{out_mp3}"'
                                                proc = await asyncio.create_subprocess_shell(cmd)
                                                await proc.communicate()
                                                if os.path.exists(raw_file):
                                                    os.remove(raw_file)
                                            else:
                                                os.rename(raw_file, out_mp3)

                                            if os.path.exists(out_mp3):
                                                logging.info(f"✅ Audio Piped orqali muvaffaqiyatli yuklandi: {out_mp3}")
                                                return out_mp3, title
        except Exception as e:
            logging.warning(f"Piped API ({api_base}) xatosi: {e}")
            continue

    return None, "Audio Track"

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
            async with session.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
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
                                    return out_mp3, title
    except Exception as e:
        logging.warning(f"Cobalt API xatosi: {e}")

    return None, "Audio Track"

# ---------------------------------------------------------------------------
# 4. MEDIA YUKLASH (Instagram/TikTok/YouTube Video)
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    return await asyncio-to_thread(_download_social_video, url.strip()) if hasattr(asyncio, "to_thread") else await asyncio.get_event_loop().run_in_executor(None, _download_social_video, url.strip())

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
