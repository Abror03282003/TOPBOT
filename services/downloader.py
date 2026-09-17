import os
import glob
import shutil
import asyncio
import logging
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file, save_to_cache

# ---------------------------------------------------------------------------
# FFmpeg / FFprobe aniqlash
# ---------------------------------------------------------------------------
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        logging.info(f"imageio_ffmpeg ishlatilmoqda: {FFMPEG_PATH}")
    except Exception as e:
        logging.error(f"FFmpeg topilmadi: {e}")

if not FFPROBE_PATH and FFMPEG_PATH:
    candidate = os.path.join(os.path.dirname(FFMPEG_PATH), "ffprobe")
    FFPROBE_PATH = candidate if os.path.exists(candidate) else FFMPEG_PATH

# Pydub uchun ulaymiz (RuntimeWarning'ni yo'qotadi)
if FFMPEG_PATH:
    AudioSegment.converter = FFMPEG_PATH
if FFPROBE_PATH:
    AudioSegment.ffprobe = FFPROBE_PATH

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIES_PATH = "cookies.txt"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,   # MUHIM: haqiqiy xatoni ko'rish uchun
    'geo_bypass': True,
    'retries': 3,
    'socket_timeout': 30,
}

if FFMPEG_PATH:
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH

# Har bir urinish: (player_client ro'yxati, cookies ishlatilsinmi)
# MUHIM: android/ios cookies'ni QO'LLAMAYDI — ular cookies bilan o'tkazib yuboriladi.
CLIENT_ATTEMPTS = [
    (['web_safari'], True),
    (['web'], True),
    (['tv'], True),
    (['android', 'ios'], False),   # cookies'siz mobil klientlar
    (['mweb'], False),
    (None, False),                 # yt-dlp o'zi tanlasin
]


def _ensure_cookies_file():
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if not cookies_env:
        return
    cleaned = cookies_env.strip()
    if os.path.exists(COOKIES_PATH):
        try:
            with open(COOKIES_PATH, "r", encoding="utf-8") as f:
                if f.read().strip() == cleaned:
                    return
        except Exception:
            pass
    try:
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(cleaned)
    except Exception as e:
        logging.error(f"Cookies faylini yozishda xatolik: {e}")


def _has_cookies() -> bool:
    return os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0


def _build_opts(extra: dict, clients=None, use_cookies: bool = True) -> dict:
    _ensure_cookies_file()
    opts = {**BASE_YDL_OPTS, **extra}
    opts['user_agent'] = USER_AGENT
    if use_cookies and _has_cookies():
        opts['cookiefile'] = COOKIES_PATH
    else:
        opts.pop('cookiefile', None)
    if clients:
        opts['extractor_args'] = {'youtube': {'player_client': list(clients)}}
    else:
        opts.pop('extractor_args', None)
    return opts


def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


# ---------------------------------------------------------------------------
# QIDIRUV
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 30) -> list[dict]:

    def _search():
        base = {'extract_flat': True, 'skip_download': True, 'ignoreerrors': True}

        for clients, use_cookies in CLIENT_ATTEMPTS:
            try:
                with yt_dlp.YoutubeDL(_build_opts(base, clients, use_cookies)) as ydl:
                    res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                results = []
                if res and res.get('entries'):
                    for entry in res['entries']:
                        if entry and entry.get('id'):
                            results.append({
                                'id': entry.get('id'),
                                'title': entry.get('title', 'Unknown Title'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader') or entry.get('channel') or 'Unknown Artist'
                            })
                if results:
                    return results
            except Exception as e:
                logging.warning(f"YouTube search ({clients}) xatosi: {e}")

        # SoundCloud zaxira
        try:
            with yt_dlp.YoutubeDL(_build_opts(base, None, False)) as ydl:
                res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            results = []
            if res and res.get('entries'):
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


# ---------------------------------------------------------------------------
# AUDIO YUKLASH
# ---------------------------------------------------------------------------
def _find_downloaded(file_prefix: str) -> str | None:
    expected_mp3 = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")
    if os.path.exists(expected_mp3) and os.path.getsize(expected_mp3) > 0:
        return expected_mp3
    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
    for f in glob.glob(pattern):
        if f.endswith(('.part', '.ytdl')):
            continue
        if os.path.exists(f) and os.path.getsize(f) > 0:
            return f
    return None


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)

    cached_file_id = await get_cached_file(youtube_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if youtube_id.startswith("http"):
        url = youtube_id
        file_prefix = "sc_" + str(abs(hash(youtube_id)))[-6:]
    else:
        url = f"https://www.youtube.com/watch?v={youtube_id}"
        file_prefix = youtube_id

    def _download():
        title = "Audio Track"

        # Keng qamrovli format zanjiri — biror format albatta topiladi
        format_chain = 'bestaudio[acodec!=none]/bestaudio/best[acodec!=none]/best/worst'

        extra = {
            'format': format_chain,
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_prefix}.%(ext)s'),
            'overwrites': True,
        }

        if FFMPEG_PATH:
            extra['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        last_error = None
        for clients, use_cookies in CLIENT_ATTEMPTS:
            opts = _build_opts(extra, clients, use_cookies)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    title = info.get('title', title)
                found = _find_downloaded(file_prefix)
                if found:
                    logging.info(f"✅ Yuklandi ({clients}, cookies={use_cookies}): {found}")
                    return found, title, None
            except Exception as e:
                last_error = e
                logging.warning(f"Urinish muvaffaqiyatsiz ({clients}, cookies={use_cookies}): {e}")
                continue

        logging.error(f"❌ Barcha urinishlar muvaffaqiyatsiz. Oxirgi xato: {last_error}")
        return None, title, None

    return await asyncio.to_thread(_download)


# ---------------------------------------------------------------------------
# VIDEO / MEDIA YUKLASH
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:

    def _download():
        extra = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s.%(ext)s'),
            'max_filesize': 50 * 1024 * 1024,
            'overwrites': True,
        }
        if FFMPEG_PATH:
            extra['merge_output_format'] = 'mp4'

        for clients, use_cookies in CLIENT_ATTEMPTS:
            try:
                with yt_dlp.YoutubeDL(_build_opts(extra, clients, use_cookies)) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if not info or not isinstance(info, dict):
                        continue
                    filename = ydl.prepare_filename(info)

                base, _ = os.path.splitext(filename)
                for ext in ('.mp4', '.mkv', '.webm'):
                    if os.path.exists(base + ext) and os.path.getsize(base + ext) > 0:
                        filename = base + ext
                        break

                if os.path.exists(filename) and os.path.getsize(filename) > 0:
                    return {
                        "file_path": filename,
                        "title": info.get("title", "Video"),
                        "id": info.get("id")
                    }
            except Exception as e:
                logging.warning(f"Media urinish ({clients}) xatosi: {e}")
                continue

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
