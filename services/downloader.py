import os
import glob
import shutil
import asyncio
import logging
import subprocess
import tempfile
import base64
import requests
import yt_dlp

# ====================== FFMPEG ======================
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

# Cobalt instancelari (ishlamasa keyingi usulga o'tadi)
COBALT_INSTANCES = [
    "https://api.cobalt.tools/",
    "https://cobalt.api.scity.gov.tw/",
    "https://cobalt.v0.co/",
]


def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


def _convert_to_clean_mp3(input_file: str, output_file: str) -> bool:
    """Istalgan audio/video faylni FFmpeg orqali toza 192kbps MP3 ga o'tkazish"""
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
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
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


def _get_cookies_file() -> str | None:
    """Railway Environment Variable dan cookies.txt yaratish"""
    cookies_b64 = os.getenv("YT_COOKIES_BASE64")
    if not cookies_b64:
        return None

    try:
        content = base64.b64decode(cookies_b64).decode("utf-8")
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        return tmp.name
    except Exception as e:
        logging.error(f"Cookies decode xatosi: {e}")
        return None


# ====================== QIDIRUV ======================
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    clean_query = query.strip().lower()

    if clean_query in SEARCH_CACHE:
        logging.info(f"Qidiruv keshdan olindi: {clean_query}")
        return SEARCH_CACHE[clean_query]

    def _search():
        try:
            yt_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'skip_download': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
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
        return []

    return await asyncio.to_thread(_search)


# ====================== COBALT ======================
def _download_via_cobalt(target_url: str, out_file: str) -> tuple[bool, str]:
    """Cobalt API orqali yuklash"""
    payload = {
        "url": target_url,
        "downloadMode": "audio",
        "audioFormat": "mp3"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    temp_raw = out_file + ".raw"

    for api_url in COBALT_INSTANCES:
        try:
            res = requests.post(api_url, json=payload, headers=headers, timeout=12)
            if res.status_code in (200, 201):
                data = res.json()
                download_url = data.get("url") if data.get("status") in ["tunnel", "redirect"] else None
                if download_url:
                    r = requests.get(download_url, stream=True, timeout=50)
                    if r.status_code == 200:
                        with open(temp_raw, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=16384):
                                f.write(chunk)
                        if os.path.exists(temp_raw) and os.path.getsize(temp_raw) > 10240:
                            if _convert_to_clean_mp3(temp_raw, out_file):
                                logging.info(f"✅ Cobalt API ({api_url}) orqali yuklandi.")
                                return True, "Audio Track"
        except Exception as e:
            logging.warning(f"Cobalt API ({api_url}) xatolik: {e}")
            continue
        finally:
            if os.path.exists(temp_raw):
                try:
                    os.remove(temp_raw)
                except Exception:
                    pass

    return False, "Audio Track"


# ====================== YT-DLP (COOKIES + BYPASS) ======================
def _download_via_ytdlp_bypass(target_url: str, out_file: str) -> tuple[bool, str]:
    """yt-dlp + cookies + TV/Web Creator client"""
    cookies_file = _get_cookies_file()

    try:
        ydl_opts = {
            'format': 'ba/ba*/bestaudio/best',
            'outtmpl': out_file + ".%(ext)s",
            'quiet': True,
            'no_warnings': True,
            'overwrites': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tvhtml5', 'web_creator', 'android', 'ios']
                }
            }
        }

        if cookies_file:
            ydl_opts['cookiefile'] = cookies_file
            logging.info("Cookies ishlatilmoqda...")

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
                    logging.info("✅ yt-dlp orqali yuklandi.")
                    return True, title

    except Exception as e:
        logging.error(f"YT-DLP bypass xatosi: {e}")
    finally:
        if cookies_file and os.path.exists(cookies_file):
            try:
                os.remove(cookies_file)
            except Exception:
                pass

    return False, "Audio Track"


# ====================== SOUNDCLOUD ZAXIRA ======================
def _download_via_soundcloud_fallback(track_title: str, out_file: str) -> tuple[bool, str]:
    """YouTube blok bo'lsa SoundCloud orqali qidirib yuklash"""
    try:
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
            info = ydl.extract_info(f"scsearch1:{track_title}", download=True)
            if info and 'entries' in info and info['entries']:
                entry = info['entries'][0]
                title = entry.get('title', track_title)
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
        logging.error(f"SoundCloud fallback xatosi: {e}")
    return False, "Audio Track"


# ====================== ASOSIY YUKLASH ======================
async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str]:
    if str(video_id_or_url).startswith("http"):
        target_url = video_id_or_url
        file_prefix = "track_" + str(abs(hash(video_id_or_url)))[-8:]
    else:
        target_url = f"https://www.youtube.com/watch?v={video_id_or_url}"
        file_prefix = str(video_id_or_url)

    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    # Kesh
    if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
        logging.info(f"Qo'shiq keshdan olindi: {out_file}")
        return out_file, track_title or "Audio Track"

    def _download():
        # 1. Cobalt
        success, title = _download_via_cobalt(target_url, out_file)
        if success:
            return out_file, title

        # 2. yt-dlp + cookies
        success, title = _download_via_ytdlp_bypass(target_url, out_file)
        if success:
            return out_file, title

        # 3. SoundCloud zaxira
        if track_title:
            success, title = _download_via_soundcloud_fallback(track_title, out_file)
            if success:
                return out_file, title

        return None, "Audio Track"

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")

    if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
        logging.info(f"Video keshdan olindi: {out_file}")
        return {"file_path": out_file, "title": "Video", "id": file_prefix}

    def _download():
        payload = {"url": url, "downloadMode": "auto"}
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

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
