import os
import glob
import shutil
import asyncio
import logging
import subprocess
import requests
import yt_dlp

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

SEARCH_CACHE = {}

# RAILWAY MUHITIDAN COOKIES YARATISH
COOKIES_FILE = os.path.join(DOWNLOAD_DIR, "youtube_cookies.txt")
raw_cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()

if raw_cookies:
    try:
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            f.write(raw_cookies)
        logging.info("✅ YouTube cookies fayli Railway Environment'dan yaratildi.")
    except Exception as e:
        logging.error(f"Cookies faylini yaratishda xatolik: {e}")
        COOKIES_FILE = None
else:
    COOKIES_FILE = None

# Ishlaydigan rasmiy Cobalt API lar
COBALT_INSTANCES = [
    "https://api.cobalt.tools/",
    "https://cobalt.qoi.pku.edu.cn/"
]


def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


def _convert_to_clean_mp3(input_file: str, output_file: str) -> bool:
    try:
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", input_file,
            "-vn",
            "-ar", "44100",
            "-ac", "2",
            "-b:a", "192k",
            "-f", "mp3",
            output_file
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=35)
        if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 10240:
            if os.path.exists(input_file) and input_file != output_file:
                try:
                    os.remove(input_file)
                except Exception:
                    pass
            return True
    except Exception as e:
        logging.error(f"FFmpeg konvertatsiya xatosi: {e}")
    return False


async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    clean_query = query.strip().lower()
    
    if clean_query in SEARCH_CACHE:
        return SEARCH_CACHE[clean_query]

    def _search():
        # 1. YouTube Qidiruv
        try:
            yt_opts = {
                'quiet': True, 
                'no_warnings': True, 
                'extract_flat': True,
                'skip_download': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            if COOKIES_FILE and os.path.exists(COOKIES_FILE):
                yt_opts['cookiefile'] = COOKIES_FILE

            with yt_dlp.YoutubeDL(yt_opts) as ydl:
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
                    SEARCH_CACHE[clean_query] = results
                    return results
        except Exception as e:
            logging.error(f"YouTube qidiruv xatosi: {e}")

        # 2. SoundCloud Qidiruv zaxirasi
        try:
            yt_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'skip_download': True}
            with yt_dlp.YoutubeDL(yt_opts) as ydl:
                res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
                results = []
                if res and 'entries' in res and res['entries']:
                    for entry in res['entries']:
                        url = entry.get('url') or entry.get('webpage_url')
                        if url:
                            results.append({
                                'id': url,
                                'title': entry.get('title', 'Unknown Title'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader', 'SoundCloud')
                            })
                if results:
                    SEARCH_CACHE[clean_query] = results
                    return results
        except Exception:
            pass

        return []

    return await asyncio.to_thread(_search)


def _download_via_ytdlp_cookies(target_url: str, out_file: str) -> tuple[bool, str]:
    """Cookies fayli orqali yt-dlp yuklash (Eng ishonchli usul)"""
    if not COOKIES_FILE or not os.path.exists(COOKIES_FILE):
        return False, "Audio Track"

    try:
        ydl_opts = {
            'format': 'ba/ba*/bestaudio/best',
            'outtmpl': out_file + ".%(ext)s",
            'quiet': True,
            'no_warnings': True,
            'overwrites': True,
            'cookiefile': COOKIES_FILE
        }
        
        if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
            ydl_opts['ffmpeg_location'] = FFMPEG_PATH
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            title = info.get('title', 'Audio Track') if info else 'Audio Track'
            
            base_prefix = out_file.replace('.mp3', '')
            for f in glob.glob(f"{base_prefix}.*"):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    if not f.endswith('.mp3'):
                        _convert_to_clean_mp3(f, out_file)
                    else:
                        if f != out_file:
                            shutil.move(f, out_file)
                    logging.info("✅ YouTube cookies orqali MP3 yuklandi.")
                    return True, title
    except Exception as e:
        logging.error(f"yt-dlp cookies yuklash xatosi: {e}")

    return False, "Audio Track"


def _download_via_cobalt(target_url: str, out_file: str) -> tuple[bool, str]:
    payload = {"url": target_url, "downloadMode": "audio", "audioFormat": "mp3"}
    headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    temp_raw = out_file + ".raw"

    for api_url in COBALT_INSTANCES:
        try:
            res = requests.post(api_url, json=payload, headers=headers, timeout=12)
            if res.status_code in (200, 201):
                data = res.json()
                download_url = data.get("url") if data.get("status") in ["tunnel", "redirect"] else None
                if download_url:
                    r = requests.get(download_url, stream=True, timeout=45)
                    if r.status_code == 200:
                        with open(temp_raw, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=16384):
                                f.write(chunk)
                        if os.path.exists(temp_raw) and os.path.getsize(temp_raw) > 10240:
                            if _convert_to_clean_mp3(temp_raw, out_file):
                                logging.info(f"✅ Cobalt API ({api_url}) orqali yuklandi.")
                                return True, "Audio Track"
        except Exception:
            continue
        finally:
            if os.path.exists(temp_raw):
                try:
                    os.remove(temp_raw)
                except Exception:
                    pass
    return False, "Audio Track"


def _download_via_soundcloud(track_id_or_url: str, out_file: str) -> tuple[bool, str]:
    try:
        query = track_id_or_url if track_id_or_url.startswith("http") else f"scsearch1:{track_id_or_url}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_file + ".%(ext)s",
            'quiet': True,
            'no_warnings': True,
            'overwrites': True,
        }
        if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
            ydl_opts['ffmpeg_location'] = FFMPEG_PATH
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=True)
            title = info.get('title', 'Audio Track') if info else 'Audio Track'
            base_prefix = out_file.replace('.mp3', '')
            for f in glob.glob(f"{base_prefix}.*"):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    if not f.endswith('.mp3'):
                        _convert_to_clean_mp3(f, out_file)
                    else:
                        if f != out_file:
                            shutil.move(f, out_file)
                    logging.info("✅ SoundCloud zaxirasi orqali yuklandi.")
                    return True, title
    except Exception as e:
        logging.error(f"SoundCloud yuklash xatosi: {e}")

    return False, "Audio Track"


async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str]:
    if str(video_id_or_url).startswith("http"):
        target_url = video_id_or_url
        file_prefix = "track_" + str(abs(hash(video_id_or_url)))[-8:]
    else:
        target_url = f"https://www.youtube.com/watch?v={video_id_or_url}"
        file_prefix = str(video_id_or_url)

    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
        return out_file, track_title or "Audio Track"

    def _download():
        # 1. YouTube Cookies orqali (Railway Variable kiritilgan bo'lsa)
        success, title = _download_via_ytdlp_cookies(target_url, out_file)
        if success:
            return out_file, title

        # 2. Cobalt API orqali
        success, title = _download_via_cobalt(target_url, out_file)
        if success:
            return out_file, title

        # 3. SoundCloud zaxira manbasi orqali
        search_term = track_title or target_url
        success, title = _download_via_soundcloud(search_term, out_file)
        if success:
            return out_file, title

        return None, "Audio Track"

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")

    if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
        return {"file_path": out_file, "title": "Video", "id": file_prefix}

    def _download():
        payload = {"url": url, "downloadMode": "auto"}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        
        for api_url in COBALT_INSTANCES:
            try:
                res = requests.post(api_url, json=payload, headers=headers, timeout=12)
                if res.status_code in (200, 201):
                    data = res.json()
                    dl_url = data.get("url") if data.get("status") in ["tunnel", "redirect"] else None
                    if dl_url:
                        r = requests.get(dl_url, stream=True, timeout=60)
                        if r.status_code == 200:
                            with open(out_file, 'wb') as f:
                                for chunk in r.iter_content(chunk_size=16384):
                                    f.write(chunk)
                            if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                                return {"file_path": out_file, "title": "Video", "id": file_prefix}
            except Exception:
                continue

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
