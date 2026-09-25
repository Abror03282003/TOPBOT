import os
import glob
import shutil
import asyncio
import logging
import yt_dlp

# FFMPEG va FFPROBE joylashuvini aniqlash
FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or shutil.which("ffmpeg") or "/usr/bin/ffprobe"

if not os.path.exists(FFMPEG_PATH):
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        FFPROBE_PATH = os.path.join(os.path.dirname(FFMPEG_PATH), "ffprobe")
    except Exception:
        pass

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIES_PATH = "cookies.txt"

# Qidiruv natijalarini xotirada saqlash uchun kesh
SEARCH_CACHE = {}

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'geo_bypass': True,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
}

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH


def _ensure_cookies_file():
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
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    clean_query = query.strip().lower()
    
    if clean_query in SEARCH_CACHE:
        logging.info(f"Qidiruv keshdan olindi: {clean_query}")
        return SEARCH_CACHE[clean_query]

    search_opts = _get_active_opts({
        'extract_flat': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web']
            }
        }
    })

    def _search():
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
                    SEARCH_CACHE[clean_query] = results
                    return results
        except Exception as e:
            logging.error(f"YouTube search error: {e}")

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
                if results:
                    SEARCH_CACHE[clean_query] = results
                return results
        except Exception as e:
            logging.error(f"SoundCloud search error: {e}")
            return []

    return await asyncio.to_thread(_search)


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str]:
    if str(video_id_or_url).startswith("http"):
        url = video_id_or_url
        file_prefix = "sc_" + str(abs(hash(video_id_or_url)))[-6:]
    else:
        url = f"https://www.youtube.com/watch?v={video_id_or_url}"
        file_prefix = str(video_id_or_url)

    # KESH TEKSHIRUVI
    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
    files = glob.glob(pattern)
    for f in files:
        if os.path.getsize(f) > 0 and not f.endswith(('.part', '.ytdl')):
            logging.info(f"Qo'shiq keshdan olindi: {f}")
            return f, "Audio Track"

    def _download():
        title = "Audio Track"

        # 1-Urinish: universal formatlar ro'yxati va mweb/android client
        ydl_opts_mp3 = _get_active_opts({
            'format': 'bestaudio/ba/m4a/mp3/best',
            'outtmpl': f'{DOWNLOAD_DIR}/{file_prefix}.%(ext)s',
            'extractor_args': {
                'youtube': {
                    'player_client': ['mweb', 'android', 'web']
                }
            },
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts_mp3) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    title = info.get('title', 'Audio Track')
        except Exception as e:
            logging.error(f"1-bosqich (MP3) yuklash xatosi: {e}")

        files = glob.glob(pattern)
        for f in files:
            if os.path.getsize(f) > 0 and not f.endswith(('.part', '.ytdl')):
                return f, title

        # 2-Urinish: agar muammo bo'lsa, har qanday eng kichik video/audio oqimni olish
        ydl_opts_raw = _get_active_opts({
            'format': 'worst/best',
            'outtmpl': f'{DOWNLOAD_DIR}/{file_prefix}.%(ext)s',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web']
                }
            },
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts_raw) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    title = info.get('title', 'Audio Track')
        except Exception as e:
            logging.error(f"2-bosqich (Raw Audio) yuklash xatosi: {e}")

        files = glob.glob(pattern)
        for f in files:
            if os.path.getsize(f) > 0 and not f.endswith(('.part', '.ytdl')):
                return f, title

        return None, title

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    
    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
    files = glob.glob(pattern)
    for f in files:
        if os.path.getsize(f) > 0 and not f.endswith(('.part', '.ytdl')):
            logging.info(f"Video keshdan olindi: {f}")
            return {
                "file_path": f,
                "title": "Video",
                "id": file_prefix
            }

    ydl_opts = _get_active_opts({
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{DOWNLOAD_DIR}/{file_prefix}.%(ext)s',
        'max_filesize': 50 * 1024 * 1024,
    })

    def _download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "Video") if info else "Video"
                video_id = info.get("id", file_prefix) if info else file_prefix
                
                pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
                files = glob.glob(pattern)
                for f in files:
                    if os.path.getsize(f) > 0 and not f.endswith(('.part', '.ytdl')):
                        return {
                            "file_path": f,
                            "title": title,
                            "id": video_id
                        }
        except Exception as e:
            logging.error(f"Media download error: {e}")

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
