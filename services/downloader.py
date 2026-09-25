import os
import glob
import shutil
import asyncio
import logging
import requests
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

# Qidiruv keshlanishi
SEARCH_CACHE = {}

# Ishonchli va faol public instansiyalar
PUBLIC_APIS = [
    "https://api.cobalt.tools/",
    "https://cobalt-api.kwiatekm.com/",
    "https://co.wuk.sh/"
]

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.no-logs.how",
    "https://invidious.projectsegfau.lt"
]

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

    def _search():
        # YouTube Search (Flat extraction)
        try:
            yt_opts = {
                'quiet': True, 
                'no_warnings': True, 
                'extract_flat': True,
                'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15'
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
            logging.error(f"YouTube search error: {e}")

        return []

    return await asyncio.to_thread(_search)


def _download_via_invidious(video_id: str, out_file: str) -> tuple[bool, str]:
    """Invidious proxy orqali IP bloklanmasdan yuklash"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for instance in INVIDIOUS_INSTANCES:
        try:
            url = f"{instance}/api/v1/videos/{video_id}"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                title = data.get("title", "Audio Track")
                adaptive = data.get("adaptiveFormats", [])
                audio_streams = [f for f in adaptive if "audio" in f.get("type", "")]
                if audio_streams:
                    stream_url = audio_streams[0].get("url")
                    r = requests.get(stream_url, stream=True, timeout=30)
                    if r.status_code == 200:
                        with open(out_file, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                            logging.info(f"✅ Invidious orqali yuklandi: {instance}")
                            return True, title
        except Exception as e:
            continue
    return False, "Audio Track"


def _download_via_cobalt(target_url: str, out_file: str) -> bool:
    """Cobalt API orqali yuklash"""
    payload = {
        "url": target_url,
        "downloadMode": "audio",
        "audioFormat": "mp3"
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    for api_url in PUBLIC_APIS:
        try:
            res = requests.post(api_url, json=payload, headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                download_url = data.get("url") if data.get("status") in ["tunnel", "redirect"] else None
                if download_url:
                    r = requests.get(download_url, stream=True, timeout=30)
                    if r.status_code == 200:
                        with open(out_file, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                            logging.info(f"✅ Cobalt ({api_url}) orqali yuklandi.")
                            return True
        except Exception:
            continue
    return False


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str]:
    if str(video_id_or_url).startswith("http"):
        target_url = video_id_or_url
        video_id = str(video_id_or_url)
        file_prefix = "track_" + str(abs(hash(video_id_or_url)))[-8:]
    else:
        target_url = f"https://www.youtube.com/watch?v={video_id_or_url}"
        video_id = str(video_id_or_url)
        file_prefix = video_id

    # 1. Keshni tekshirish
    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
    files = glob.glob(pattern)
    for f in files:
        if os.path.getsize(f) > 10240 and not f.endswith(('.part', '.ytdl')):
            logging.info(f"Qo'shiq keshdan olindi: {f}")
            return f, "Audio Track"

    def _download():
        out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

        # 1-Bosqich: Invidious Proxy (Kafolatli va IP-blokdan xoli)
        if not target_url.startswith("http://") and not target_url.startswith("https://") or "youtube" in target_url:
            success, title = _download_via_invidious(video_id, out_file)
            if success:
                return out_file, title

        # 2-Bosqich: Cobalt API
        if _download_via_cobalt(target_url, out_file):
            return out_file, "Audio Track"

        # 3-Bosqich: yt-dlp (iOS Client Emulation bilan)
        try:
            ydl_opts = {
                'format': 'ba/ba*/bestaudio/best',
                'outtmpl': f'{DOWNLOAD_DIR}/{file_prefix}.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios', 'android', 'mweb']
                    }
                }
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
                
                files = glob.glob(pattern)
                for f in files:
                    if os.path.getsize(f) > 10240 and not f.endswith(('.part', '.ytdl')):
                        return f, title
        except Exception as e:
            logging.error(f"yt-dlp xatoligi: {e}")

        return None, "Audio Track"

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    
    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
    files = glob.glob(pattern)
    for f in files:
        if os.path.getsize(f) > 10240 and not f.endswith(('.part', '.ytdl')):
            logging.info(f"Video keshdan olindi: {f}")
            return {"file_path": f, "title": "Video", "id": file_prefix}

    def _download():
        out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")
        if _download_via_cobalt(url, out_file):
            return {"file_path": out_file, "title": "Video", "id": file_prefix}

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
