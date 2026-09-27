import os
import glob
import shutil
import asyncio
import logging
import subprocess
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

SEARCH_CACHE = {}

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.privacydev.net",
    "https://pipedapi.mha.fi"
]

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.no-logs.how"
]

COBALT_APIS = [
    "https://api.cobalt.tools/",
    "https://co.wuk.sh/"
]


def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


def _convert_to_clean_mp3(input_file: str, output_file: str) -> bool:
    """Audio oqimini FFmpeg orqali toza MP3 ga o'tkazish"""
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
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 10240:
            if os.path.exists(input_file) and input_file != output_file:
                os.remove(input_file)
            return True
    except Exception as e:
        logging.error(f"FFmpeg konvertatsiya xatosi: {e}")
    return False


async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    clean_query = query.strip().lower()
    
    if clean_query in SEARCH_CACHE:
        logging.info(f"Qidiruv keshdan olindi: {clean_query}")
        return SEARCH_CACHE[clean_query]

    def _search():
        # 1. yt-dlp flat extraction (O'zbekcha va barcha tillardagi qo'shiqlar uchun eng mos)
        try:
            yt_opts = {
                'quiet': True, 
                'no_warnings': True, 
                'extract_flat': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
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
            logging.error(f"yt-dlp search error: {e}")

        # 2. Piped API (Zaxira qidiruv)
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/search?q={query}&filter=all"
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    items = res.json().get("items", [])
                    results = []
                    for item in items[:limit]:
                        v_id = item.get("url", "").replace("/watch?v=", "")
                        if v_id:
                            results.append({
                                'id': v_id,
                                'title': item.get('title', 'Unknown Title'),
                                'duration': format_duration(item.get('duration', 0)),
                                'uploader': item.get('uploaderName', 'YouTube')
                            })
                    if results:
                        SEARCH_CACHE[clean_query] = results
                        return results
            except Exception:
                continue

        return []

    return await asyncio.to_thread(_search)


def _download_via_piped(video_id: str, out_file: str) -> tuple[bool, str]:
    temp_raw = out_file + ".raw"
    for instance in PIPED_INSTANCES:
        try:
            url = f"{instance}/streams/{video_id}"
            res = requests.get(url, timeout=6)
            if res.status_code == 200:
                data = res.json()
                title = data.get("title", "Audio Track")
                audio_streams = data.get("audioStreams", [])
                if audio_streams:
                    stream_url = audio_streams[0].get("url")
                    r = requests.get(stream_url, stream=True, timeout=30)
                    if r.status_code == 200:
                        with open(temp_raw, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        if os.path.exists(temp_raw) and os.path.getsize(temp_raw) > 10240:
                            if _convert_to_clean_mp3(temp_raw, out_file):
                                logging.info(f"✅ Piped orqali MP3 yuklandi ({instance})")
                                return True, title
        except Exception:
            continue
        finally:
            if os.path.exists(temp_raw):
                try:
                    os.remove(temp_raw)
                except Exception:
                    pass
    return False, "Audio Track"


def _download_via_invidious(video_id: str, out_file: str) -> tuple[bool, str]:
    temp_raw = out_file + ".raw"
    headers = {"User-Agent": "Mozilla/5.0"}
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
                        with open(temp_raw, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        if os.path.exists(temp_raw) and os.path.getsize(temp_raw) > 10240:
                            if _convert_to_clean_mp3(temp_raw, out_file):
                                logging.info(f"✅ Invidious orqali MP3 yuklandi ({instance})")
                                return True, title
        except Exception:
            continue
        finally:
            if os.path.exists(temp_raw):
                try:
                    os.remove(temp_raw)
                except Exception:
                    pass
    return False, "Audio Track"


def _download_via_cobalt(target_url: str, out_file: str) -> bool:
    payload = {"url": target_url, "downloadMode": "audio", "audioFormat": "mp3"}
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    for api_url in COBALT_APIS:
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

    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")
    if os.path.exists(pattern) and os.path.getsize(pattern) > 10240:
        logging.info(f"Qo'shiq keshdan olindi: {pattern}")
        return pattern, "Audio Track"

    def _download():
        out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

        # 1-Bosqich: Piped API
        if not target_url.startswith("http://") and not target_url.startswith("https://") or "youtube" in target_url:
            success, title = _download_via_piped(video_id, out_file)
            if success:
                return out_file, title

        # 2-Bosqich: Invidious API
        if not target_url.startswith("http://") and not target_url.startswith("https://") or "youtube" in target_url:
            success, title = _download_via_invidious(video_id, out_file)
            if success:
                return out_file, title

        # 3-Bosqich: Cobalt API
        if _download_via_cobalt(target_url, out_file):
            return out_file, "Audio Track"

        return None, "Audio Track"

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")
    
    if os.path.exists(pattern) and os.path.getsize(pattern) > 10240:
        logging.info(f"Video keshdan olindi: {pattern}")
        return {"file_path": pattern, "title": "Video", "id": file_prefix}

    def _download():
        out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")
        if _download_via_cobalt(url, out_file):
            return {"file_path": out_file, "title": "Video", "id": file_prefix}

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
