import os
import glob
import shutil
import asyncio
import logging
import time
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file, save_to_cache

FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or shutil.which("ffmpeg") or "/usr/bin/ffprobe"

if not os.path.exists(FFMPEG_PATH):
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
        possible_ffprobe = os.path.join(ffmpeg_dir, "ffprobe")
        if os.path.exists(possible_ffprobe):
            FFPROBE_PATH = possible_ffprobe
        else:
            FFPROBE_PATH = FFMPEG_PATH
    except Exception as e:
        logging.warning(f"imageio_ffmpeg yuklashda ogohlantirish: {e}")

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    AudioSegment.converter = FFMPEG_PATH
if FFPROBE_PATH and os.path.exists(FFPROBE_PATH):
    AudioSegment.ffprobe = FFPROBE_PATH

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIES_PATH = os.path.join(DOWNLOAD_DIR, "cookies.txt")

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
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if cookies_env:
        cookies_env_cleaned = cookies_env.strip()
        if os.path.exists(COOKIES_PATH):
            try:
                with open(COOKIES_PATH, "r", encoding="utf-8") as f:
                    if f.read().strip() == cookies_env_cleaned:
                        return
            except Exception:
                pass
        try:
            with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                f.write(cookies_env_cleaned)
            logging.info("✅ Cookies fayli YOUTUBE_COOKIES dan yaratildi.")
        except Exception as e:
            logging.error(f"Cookies yozishda xatolik: {e}")


def _get_active_opts(extra_opts: dict) -> dict:
    _ensure_cookies_file()
    opts = {**BASE_YDL_OPTS, **extra_opts}
    if os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0:
        opts['cookiefile'] = COOKIES_PATH
    return opts


def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    search_opts = _get_active_opts({
        'extract_flat': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb']
            }
        }
    })

    def _search():
        # 1. YouTube Qidiruvi
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
                                'uploader': entry.get('uploader', 'YouTube')
                            })
                if results:
                    return results
        except Exception as e:
            logging.error(f"YouTube qidiruv xatosi: {e}")

        # 2. SoundCloud Qidiruvi
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
                                'uploader': entry.get('uploader', 'SoundCloud')
                            })
                return results
        except Exception as e:
            logging.error(f"SoundCloud qidiruv xatosi: {e}")
            return []

    return await asyncio.to_thread(_search)


def _download_soundcloud_fallback(search_title: str, out_prefix: str) -> tuple[str | None, str]:
    """YouTube IP bloklaganda, berilgan trek nomi bo'yicha SoundCloud'dan yuklaydi"""
    if not search_title or search_title == "Audio Track":
        return None, "Audio Track"

    try:
        # Fayl nomlarining to'qnashmasligi uchun unikal ID qo'shamiz
        unique_outtmpl = os.path.join(DOWNLOAD_DIR, f'{out_prefix}_sc_{int(time.time()*1000)}.%(ext)s')
        
        sc_opts = _get_active_opts({
            'format': 'bestaudio/best',
            'outtmpl': unique_outtmpl,
            'default_search': 'scsearch',
        })
        if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
            sc_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(sc_opts) as ydl:
            info = ydl.extract_info(f"scsearch1:{search_title}", download=True)
            if info and 'entries' in info and info['entries']:
                entry = info['entries'][0]
                title = entry.get('title', search_title)
                
                # Saqlangan MP3 faylini izlab topish
                sc_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{out_prefix}_sc_*.mp3"))
                if sc_files:
                    latest_file = max(sc_files, key=os.path.getmtime)
                    if os.path.getsize(latest_file) > 10240:
                        logging.info(f"✅ SoundCloud zaxirasi orqali trek yuklandi: {title}")
                        return latest_file, title
    except Exception as e:
        logging.error(f"SoundCloud zaxira xatosi: {e}")
    return None, search_title


async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)
    
    # Bazadan keshni tekshirish
    cached_file_id = await get_cached_file(youtube_id)
    if cached_file_id:
        return None, track_title or "Audio Track", cached_file_id

    # Aniq unikal fayl prefiksi
    file_prefix = f"track_{youtube_id}_{int(time.time())}"

    def _download():
        title = track_title or "Audio Track"

        # 1. YouTube orqali yuklab ko'rish
        if str(video_id_or_url).startswith("http"):
            url = video_id_or_url
        else:
            url = f"https://www.youtube.com/watch?v={video_id_or_url}"

        ydl_opts_fast = _get_active_opts({
            'format': 'ba/ba*/bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_prefix}.%(ext)s'),
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'tv', 'mweb']
                }
            }
        })

        if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
            ydl_opts_fast['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        try:
            with yt_dlp.YoutubeDL(ydl_opts_fast) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    title = info.get('title', title)
        except Exception as e:
            logging.error(f"YouTube yuklash xatosi: {e}")

        expected_mp3 = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")
        if os.path.exists(expected_mp3) and os.path.getsize(expected_mp3) > 10240:
            return expected_mp3, title, None

        # 2. Agar YouTube bloklasa va video_id orqali nom chiqqan bo'lsa yoki track_title bo'lsa
        sc_file, sc_title = _download_soundcloud_fallback(title, file_prefix)
        if sc_file:
            return sc_file, sc_title, None

        return None, title, None

    return await asyncio.to_thread(_download)
