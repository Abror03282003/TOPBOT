import os
import glob
import shutil
import asyncio
import logging
import aiohttp
from pydub import AudioSegment
from youtube_downloader import download_youtube_audio

# FFmpeg va FFprobe yo'llarini avtomatik aniqlash
FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or shutil.which("ffmpeg") or "/usr/bin/ffprobe"

if not os.path.exists(FFMPEG_PATH):
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        FFPROBE_PATH = os.path.join(os.path.dirname(FFMPEG_PATH), "ffprobe")
    except Exception:
        pass

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    AudioSegment.converter = FFMPEG_PATH
if FFPROBE_PATH and os.path.exists(FFPROBE_PATH):
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
# QIDIRUV (Search)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    
    import yt_dlp
    
    def _search_sync():
        opts = {
            'extract_flat': True,
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'tvhtml5', 'web']
                }
            }
        }
        
        # 1-Urinish: YouTube bo'yicha qidirish
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
                if items:
                    return items
        except Exception as e:
            logging.warning(f"YouTube search error: {e}")

        # 2-Urinish: SoundCloud
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
                items = []
                if res and 'entries' in res:
                    for entry in res['entries']:
                        if entry:
                            sc_url = entry.get('url') or entry.get('webpage_url') or entry.get('id')
                            if sc_url:
                                items.append({
                                    'id': sc_url,
                                    'title': entry.get('title', 'Unknown Track'),
                                    'duration': format_duration(entry.get('duration', 0)),
                                    'uploader': entry.get('uploader') or 'SoundCloud'
                                })
                return items
        except Exception as e:
            logging.error(f"SoundCloud search error: {e}")

        return []

    return await asyncio.to_thread(_search_sync)


# ---------------------------------------------------------------------------
# COBALT API FALLBACK (Yangilangan ishchi domenlar)
# ---------------------------------------------------------------------------
async def _download_via_cobalt(video_id_or_url: str) -> str | None:
    target_url = video_id_or_url if str(video_id_or_url).startswith("http") else f"https://www.youtube.com/watch?v={video_id_or_url}"
    payload = {
        "url": target_url,
        "downloadMode": "audio",
        "audioFormat": "mp3",
        "audioBitrate": "192"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    instances = [
        "https://api.cobalt.tools",
        "https://cobalt.stream",
        "https://cobalt-api.mha.fi"
    ]

    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in instances:
            try:
                endpoint = f"{instance}/api/json" if "cobalt.tools" in instance else f"{instance}/"
                async with session.post(endpoint, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        stream_url = data.get("url")
                        if not stream_url:
                            continue

                        output_path = os.path.join(DOWNLOAD_DIR, f"cobalt_{abs(hash(video_id_or_url))}.mp3")
                        async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=40)) as s_resp:
                            if s_resp.status == 200:
                                with open(output_path, "wb") as f:
                                    async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                        f.write(chunk)
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                    logging.info(f"✅ Cobalt API orqali yuklandi: {output_path}")
                                    return output_path
            except Exception as e:
                logging.warning(f"Cobalt instance ({instance}) xatosi: {e}")
                continue

    return None


# ---------------------------------------------------------------------------
# AUDIO YUKLASH
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None, *args, **kwargs) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)
    title_result = track_title or "Audio Track"

    # Keshni tekshirish (Bazadan noto'g'ri fayl qaytmasligi uchun)
    try:
        from database import get_cached_file
        cached_file_id = await get_cached_file(youtube_id)
        if cached_file_id:
            return None, title_result, cached_file_id
    except Exception as e:
        logging.warning(f"Keshni tekshirishda xatolik: {e}")

    target_url = youtube_id if youtube_id.startswith("http") else f"https://www.youtube.com/watch?v={youtube_id}"
    
    # 1. Cobalt API orqali sinab ko'rish (Railway IP blokini aylanib o'tish uchun eng tezkor yo'l)
    cobalt_path = await _download_via_cobalt(target_url)
    if cobalt_path:
        return cobalt_path, title_result, None

    # 2. youtube_downloader.py (yt-dlp + cookies)
    try:
        file_path = await asyncio.to_thread(download_youtube_audio, target_url, DOWNLOAD_DIR)
        if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 10240:
            return file_path, title_result, None
    except Exception as e:
        logging.warning(f"youtube_downloader ishlamadi: {e}")

    return None, title_result, None


# ---------------------------------------------------------------------------
# VIDEO YUKLASH
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    import yt_dlp
    
    file_prefix = f"video_{abs(hash(url))}"
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")
    
    def _download_video():
        opts = {
            'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
            'outtmpl': outtmpl,
            'quiet': True,
            'max_filesize': 50 * 1024 * 1024,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'tvhtml5']
                }
            }
        }
        if FFMPEG_PATH:
            opts['ffmpeg_location'] = FFMPEG_PATH

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Video') if info else 'Video'
                video_id = info.get('id', file_prefix) if info else file_prefix
                
                pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
                files = glob.glob(pattern)
                for f in files:
                    if os.path.getsize(f) > 10240 and not f.endswith(('.part', '.ytdl')):
                        return {"file_path": f, "title": title, "id": video_id}
        except Exception as e:
            logging.error(f"Media yuklash xatosi: {e}")

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download_video)
