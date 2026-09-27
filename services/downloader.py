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
    """Saniyalarni MM:SS formatiga o'tkazadi."""
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"


# ---------------------------------------------------------------------------
# QIDIRUV (Search) - YouTube va SoundCloud
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
                    'player_client': ['mweb', 'android', 'ios']
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

        # 2-Urinish: SoundCloud bo'yicha qidirish (agar YouTube ishlamasa)
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
# COBALT API FALLBACK (YouTube bloklaganda zaxira yuklovchi)
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
        "Content-Type": "application/json"
    }

    instances = [
        "https://co.wuk.sh/api/json",
        "https://api.cobalt.tools/api/json"
    ]

    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in instances:
            try:
                async with session.post(instance, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        stream_url = data.get("url")
                        if not stream_url:
                            continue

                        output_path = os.path.join(DOWNLOAD_DIR, f"cobalt_{abs(hash(video_id_or_url))}.mp3")
                        async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=30)) as s_resp:
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
# AUDIO YUKLASH (Asosiy funksiya - track_title, *args, **kwargs moslashtirilgan)
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None, *args, **kwargs) -> tuple[str | None, str, str | None]:
    """
    1-Bosqich: Keshni tekshirish (database.get_cached_file)
    2-Bosqich: youtube_downloader.py orqali yuklash
    3-Bosqich: Cobalt API zaxirasi
    Qaytaradi: (fayl_yo'li, trek_nomi, cached_file_id)
    """
    youtube_id = str(video_id_or_url)
    title_result = track_title or "Audio Track"

    # 1. Keshni tekshirish (agar avval yuklangan bo'lsa)
    try:
        from database import get_cached_file
        cached_file_id = await get_cached_file(youtube_id)
        if cached_file_id:
            return None, title_result, cached_file_id
    except Exception as e:
        logging.warning(f"Keshni tekshirishda xatolik: {e}")

    target_url = youtube_id if youtube_id.startswith("http") else f"https://www.youtube.com/watch?v={youtube_id}"
    
    # 2. youtube_downloader.py orqali yuklab olish
    try:
        file_path = await asyncio.to_thread(download_youtube_audio, target_url, DOWNLOAD_DIR)
        if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 10240:
            return file_path, title_result, None
    except Exception as e:
        logging.warning(f"youtube_downloader ishlamadi, Cobalt API ga o'tilmoqda: {e}")

    # 3. Cobalt API orqali harakat qilib ko'rish
    cobalt_path = await _download_via_cobalt(target_url)
    if cobalt_path:
        return cobalt_path, title_result, None

    return None, title_result, None


# ---------------------------------------------------------------------------
# VIDEO / MEDIA YUKLASH
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
                    'player_client': ['mweb', 'android']
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
