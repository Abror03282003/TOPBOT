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
COOKIES_PATH = "cookies.txt"

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'geo_bypass': True,
}

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH


def _ensure_cookies_file():
    """Railway muhitidagi YOUTUBE_COOKIES o'zgaruvchisidan cookies.txt faylini yaratish."""
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if cookies_env:
        try:
            with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                f.write(cookies_env.strip())
        except Exception as e:
            logging.error(f"Cookies faylini yozishda xatolik: {e}")


def _get_active_opts(extra_opts: dict) -> dict:
    _ensure_cookies_file()
    opts = {**BASE_YDL_OPTS, **extra_opts}
    if os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0:
        opts['cookiefile'] = COOKIES_PATH
    return opts


def format_duration(seconds: int) -> str:
    """Saniyalarni daqiqa:soniya formatiga o'tkazish."""
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    """YouTube va SoundCloud orqali 30 tagacha qo'shiqni tezkor qidiradi."""
    search_opts = _get_active_opts({
        'extract_flat': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'android', 'ios', 'web']
            }
        }
    })

    def _search():
        # 1-urinish: YouTube bo'yicha
        try:
            with yt_dlp.YoutubeDL(search_opts) as ydl:
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
                if results:
                    return results
        except Exception as e:
            logging.error(f"YouTube search error: {e}")

        # 2-urinish: SoundCloud bo'yicha
        try:
            sc_opts = _get_active_opts({'extract_flat': True})
            with yt_dlp.YoutubeDL(sc_opts) as ydl:
                res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
                results = []
                if res and 'entries' in res and res['entries']:
                    for entry in res['entries']:
                        if entry:
                            url_or_id = entry.get('url') or entry.get('webpage_url') or entry.get('id')
                            results.append({
                                'id': url_or_id,
                                'title': entry.get('title', 'Unknown Title'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader', 'Unknown Artist')
                            })
                return results
        except Exception as e:
            logging.error(f"SoundCloud search error: {e}")
            return []

    return await asyncio.to_thread(_search)


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    """
    Audio yuklab olish.
    Ketma-ketlik:
    1. Baza (kesh)
    2. Cobalt API (Blokirovkasiz)
    3. Invidious API
    4. yt-dlp (Zaxira)
    """
    youtube_id = str(video_id_or_url)

    # 1-Bosqich: Keshni tekshirish (0.5s)
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

    # 2-Bosqich: Cobalt API orqali yuklab olish
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
            async with session.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=12) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    audio_link = data.get("url")
                    if audio_link:
                        async with session.get(audio_link, timeout=30) as file_resp:
                            if file_resp.status == 200:
                                with open(output_path, "wb") as f:
                                    f.write(await file_resp.read())
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                    logging.info("✅ Audio Cobalt API orqali yuklab olindi.")
                                    return output_path, "Audio Track", None
        except Exception as e:
            logging.warning(f"Cobalt API xatosi: {e}")

    # 3-Bosqich: Invidious API orqali yuklab olish
    fallback_file, fallback_title = await _download_via_invidious(youtube_id, file_prefix)
    if fallback_file and os.path.exists(fallback_file):
        return fallback_file, fallback_title, None

    # 4-Bosqich: Standart yt-dlp orqali yuklash (Zaxira)
    def _yt_dlp_download():
        title = "Audio Track"
        ydl_opts = _get_active_opts({
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_prefix}.%(ext)s'),
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'mweb']
                }
            }
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                if info and isinstance(info, dict):
                    title = info.get('title', 'Audio Track')
        except Exception as e:
            logging.error(f"yt-dlp yuklash xatosi: {e}")

        pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
        files = glob.glob(pattern)
        for f in files:
            if os.path.getsize(f) > 0:
                return f, title, None

        return None, title, None

    return await asyncio.to_thread(_yt_dlp_download)


async def _download_via_invidious(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    """Invidious ochiq serverlari orqali zaxira yuklash."""
    invidious_instances = [
        "https://invidious.flokinet.to",
        "https://invidious.privacydev.net",
        "https://invidious.drgns.space",
        "https://inv.nadeko.net",
    ]
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    async with aiohttp.ClientSession() as session:
        for instance in invidious_instances:
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
                            async with session.get(audio_url, timeout=20) as stream_resp:
                                if stream_resp.status == 200:
                                    with open(output_path, "wb") as f:
                                        f.write(await stream_resp.read())
                                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                        logging.info("✅ Audio Invidious orqali yuklab olindi.")
                                        return output_path, title
            except Exception:
                continue

    return None, "Audio Track"


async def download_media(url: str) -> dict:
    """Video yuklab olish (YouTube / Instagram / TikTok)."""
    ydl_opts = _get_active_opts({
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s.%(ext)s'),
        'max_filesize': 50 * 1024 * 1024,
        'merge_output_format': 'mp4',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'mweb'],
            }
        }
    })

    def _download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    filename = ydl.prepare_filename(info)
                    
                    base, _ = os.path.splitext(filename)
                    if os.path.exists(f"{base}.mp4"):
                        filename = f"{base}.mp4"

                    if os.path.exists(filename) and os.path.getsize(filename) > 0:
                        return {
                            "file_path": filename,
                            "title": info.get("title", "Video"),
                            "id": info.get("id")
                        }
        except Exception as e:
            logging.error(f"Media download error: {e}")

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
