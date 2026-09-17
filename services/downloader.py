import os
import glob
import shutil
import asyncio
import logging
import urllib.parse
import yt_dlp

# FFmpeg va FFprobe tizim yo'llarini to'g'ri aniqlash
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

DOWNLOAD_DIR = "downloads"
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
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    """YouTube va SoundCloud orqali 30 tagacha qo'shiqni qidiradi."""
    search_opts = _get_active_opts({
        'extract_flat': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'mweb', 'web']
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


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str]:
    """YouTube ID yoki SoundCloud URL orqali audio yuklab olish."""
    if str(video_id_or_url).startswith("http"):
        url = video_id_or_url
        file_prefix = "sc_" + str(hash(video_id_or_url))[-6:]
    else:
        url = f"https://www.youtube.com/watch?v={video_id_or_url}"
        file_prefix = str(video_id_or_url)

    def _download():
        title = "Audio Track"

        # 1-Bosqich: MP3 ga konvertatsiya qilib yuklash
        ydl_opts_mp3 = _get_active_opts({
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_DIR}/{file_prefix}.%(ext)s',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'mweb', 'web']
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

        # Tekshiramiz: fayl saqlandimi?
        pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
        files = glob.glob(pattern)
        for f in files:
            if os.path.getsize(f) > 0:
                return f, title

        # 2-Bosqich: Original ko'rinishida yuklash (Konvertatsiyasiz: har qanday audio format)
        ydl_opts_raw = _get_active_opts({
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_DIR}/{file_prefix}.%(ext)s',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'mweb', 'web']
                }
            }
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts_raw) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    title = info.get('title', 'Audio Track')
        except Exception as e:
            logging.error(f"2-bosqich (Raw Audio) yuklash xatosi: {e}")

        # Qayta tekshirish
        files = glob.glob(pattern)
        for f in files:
            if os.path.getsize(f) > 0:
                return f, title

        # 3-Bosqich: Oxirgi chora - Papkadagi har qanday so'nggi yuklangan fayl
        all_files = glob.glob(os.path.join(DOWNLOAD_DIR, "*"))
        if all_files:
            latest_file = max(all_files, key=os.path.getmtime)
            if os.path.getsize(latest_file) > 0:
                return latest_file, title

        return None, title

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    """Video yuklab olish (YouTube/Instagram)"""
    ydl_opts = _get_active_opts({
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'max_filesize': 50 * 1024 * 1024,
        'merge_output_format': 'mp4',
    })

    def _download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and isinstance(info, dict):
                    filename = ydl.prepare_filename(info)
                    
                    # Agar birikishdan keyin mp4 bo'lgan bo'lsa
                    base, _ = os.path.splitext(filename)
                    if os.path.exists(f"{base}.mp4"):
                        filename = f"{base}.mp4"

                    return {
                        "file_path": filename,
                        "title": info.get("title", "Video"),
                        "id": info.get("id")
                    }
        except Exception as e:
            logging.error(f"Media download error: {e}")

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
