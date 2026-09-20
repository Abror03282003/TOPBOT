import os
import glob
import shutil
import asyncio
import logging
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
COOKIES_FILE = os.path.abspath("cookies.txt")

cookies_env = os.environ.get("YOUTUBE_COOKIES")
if cookies_env:
    try:
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            f.write(cookies_env.strip())
        logging.info("🍪 Cookies muvaffaqiyatli yuklandi.")
    except Exception as e:
        logging.error(f"Cookies yozishda xato: {e}")


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        minutes = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{minutes}:{secs:02d}"
    except Exception:
        return "0:00"


def _get_base_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'user_agent': USER_AGENT,
    }
    if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
        opts['cookiefile'] = COOKIES_FILE
    return opts


# ---------------------------------------------------------------------------
# 2. QIDIRUV
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    search_query = query.strip()
    if not search_query:
        return []
    return await asyncio.to_thread(_search_tracks_sync, search_query, limit)


def _search_tracks_sync(query: str, limit: int) -> list[dict]:
    # 1. YouTube Qidiruv
    opts = _get_base_opts()
    opts.update({
        'extract_flat': True,
        'skip_download': True,
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry and entry.get('id'):
                        title = entry.get('title', 'Unknown Track')
                        uploader = entry.get('uploader') or 'YouTube'
                        items.append({
                            'id': entry.get('id'),
                            'title': title,
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': uploader,
                            # Qo'shiq nomi bo'yicha fallback uchun maxsus ID biriktiramiz
                            'search_meta': f"{title} {uploader}".strip()
                        })
            if items:
                return items
    except Exception as e:
        logging.warning(f"YouTube qidiruv xatosi: {e}. SoundCloud sinab ko'rilmoqda...")

    # 2. SoundCloud Qidiruv
    try:
        sc_opts = _get_base_opts()
        sc_opts.update({'extract_flat': True, 'skip_download': True})
        with yt_dlp.YoutubeDL(sc_opts) as ydl:
            res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry:
                        sc_url = entry.get('url') or entry.get('webpage_url')
                        if sc_url:
                            items.append({
                                'id': sc_url,
                                'title': entry.get('title', 'Unknown Track'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader') or 'SoundCloud'
                            })
            return items
    except Exception as e:
        logging.error(f"SoundCloud qidiruv xatosi: {e}")

    return []


# ---------------------------------------------------------------------------
# 3. AUDIO YUKLASH
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)

    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    file_path, title = await asyncio.to_thread(_download_audio_sync, track_id, track_title)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None


def _download_audio_sync(track_id: str, track_title: str = None) -> tuple[str | None, str]:
    if track_id.startswith("http://") or track_id.startswith("https://"):
        target_url = track_id
        file_prefix = f"audio_{abs(hash(track_id))}"
    else:
        target_url = f"https://www.youtube.com/watch?v={track_id}"
        file_prefix = f"audio_{track_id}"

    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")

    # 1. YouTube orqali yuklash urinishi (iOS/Android clientlar bilan)
    clients = [['ios'], ['android'], ['mweb'], ['tv_embedded']]
    for client in clients:
        opts = _get_base_opts()
        opts.update({
            'format': 'ba/ba*',
            'outtmpl': outtmpl,
            'overwrites': True,
            'extractor_args': {
                'youtube': {
                    'player_client': client,
                    'skip': ['hls', 'dash']
                }
            }
        })

        if FFMPEG_PATH:
            opts['ffmpeg_location'] = FFMPEG_PATH
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                title = info.get('title', 'Audio Track') if info else 'Audio Track'

                pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
                for f in glob.glob(pattern):
                    if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                        logging.info(f"✅ Audio YouTube orqali yuklandi: {f}")
                        return f, title
        except Exception as e:
            logging.warning(f"YouTube client {client} xatosi: {e}")
            continue

    # 2. SoundCloud orqali qidirib yuklash (YouTube bloklangan bo'lsa)
    try:
        search_query = track_title if track_title else track_id
        logging.info(f"🔄 YouTube bloklandi. SoundCloud'dan qidirilmoqda: '{search_query}'")

        sc_opts = _get_base_opts()
        sc_opts.update({
            'format': 'bestaudio/best',
            'outtmpl': outtmpl,
            'overwrites': True,
        })

        if FFMPEG_PATH:
            sc_opts['ffmpeg_location'] = FFMPEG_PATH
            sc_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(sc_opts) as ydl:
            # YouTube ID o'rniga trek NOMI bo'yicha qidiramiz
            info = ydl.extract_info(f"scsearch1:{search_query}", download=True)
            title = "Audio Track"
            if info and 'entries' in info and len(info['entries']) > 0:
                title = info['entries'][0].get('title', 'Audio Track')

            pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
            for f in glob.glob(pattern):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    logging.info(f"✅ Audio SoundCloud orqali yuklandi: {f}")
                    return f, title
    except Exception as sc_err:
        logging.error(f"SoundCloud fallback xatosi: {sc_err}")

    return None, "Audio Track"


# ---------------------------------------------------------------------------
# 4. MEDIA YUKLASH (Video)
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    return await asyncio.to_thread(_download_social_video, url.strip())


def _download_social_video(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")

    opts = _get_base_opts()
    opts.update({
        'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'max_filesize': 50 * 1024 * 1024,
    })

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
