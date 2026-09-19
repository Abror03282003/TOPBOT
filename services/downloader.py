import os
import glob
import shutil
import asyncio
import logging
import aiohttp
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file, save_to_cache

__all__ = ["search_tracks", "download_audio_by_id", "download_media"]

# ---------------------------------------------------------------------------
# FFmpeg Sozlamalari
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

# Faqat sinalgan va ishlayotgan ochiq API serverlar
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.privacydev.net"
]


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


# ---------------------------------------------------------------------------
# QIDIRUV
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/search"
                params = {"q": query.strip(), "type": "video"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = []
                        for entry in data[:limit]:
                            if entry.get("videoId"):
                                results.append({
                                    'id': entry.get("videoId"),
                                    'title': entry.get("title", "Unknown"),
                                    'duration': format_duration(entry.get("lengthSeconds", 0)),
                                    'uploader': entry.get("author", "Unknown")
                                })
                        if results:
                            return results
            except Exception:
                continue

    # Zaxira qidiruv: SoundCloud (YouTube server bloki aylanib o'tiladi)
    return await asyncio.to_thread(_search_soundcloud, query.strip(), limit)


def _search_soundcloud(query: str, limit: int) -> list[dict]:
    opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'user_agent': USER_AGENT,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry and entry.get('id'):
                        items.append({
                            'id': entry.get('url') or entry.get('id'),
                            'title': entry.get('title', 'Unknown'),
                               'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader') or 'SoundCloud'
                        })
            return items
    except Exception as e:
        logging.error(f"SoundCloud qidiruv xatosi: {e}")
        return []


# ---------------------------------------------------------------------------
# AUDIO YUKLASH
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)

    # 1. Keshni tekshirish
    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if track_id.startswith("http"):
        file_prefix = "url_" + str(abs(hash(track_id)))[-6:]
        if "v=" in track_id:
            track_id = track_id.split("v=")[1].split("&")[0]
    else:
        file_prefix = track_id

    # 2. Invidious API orqali birinchi urinish
    inv_file, title = await _download_via_invidious(track_id, file_prefix)
    if inv_file:
        return inv_file, title, None

    # 3. SoundCloud Fallback (YouTube blokidan 100% xoli)
    sc_file, sc_title = await asyncio.to_thread(_download_via_soundcloud, track_id, file_prefix)
    if sc_file:
        return sc_file, sc_title, None

    return None, "Audio Track", None


async def _download_via_invidious(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/videos/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    title = data.get("title", "Audio Track")
                    adaptive = data.get("adaptiveFormats", [])
                    audio_streams = [f for f in adaptive if "audio" in f.get("type", "")]
                    if not audio_streams:
                        continue

                    stream_url = audio_streams[0].get("url")
                    ext = audio_streams[0].get("container", "m4a")
                    raw_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_raw.{ext}")

                    async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=30)) as s_resp:
                        if s_resp.status == 200:
                            with open(raw_path, "wb") as f:
                                async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)

                            if os.path.exists(raw_path) and os.path.getsize(raw_path) > 10240:
                                mp3_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")
                                if FFMPEG_PATH:
                                    try:
                                        sound = AudioSegment.from_file(raw_path)
                                        sound.export(mp3_path, format="mp3", bitrate="192k")
                                        if os.path.exists(raw_path):
                                            os.remove(raw_path)
                                        return mp3_path, title
                                    except Exception:
                                        return raw_path, title
                                return raw_path, title
            except Exception:
                continue
    return None, "Audio Track"


def _download_via_soundcloud(query_or_url: str, file_prefix: str) -> tuple[str | None, str]:
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_sc.%(ext)s")
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'user_agent': USER_AGENT,
    }
    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    target = query_or_url if query_or_url.startswith("http") else f"scsearch1:{query_or_url}"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=True)
            title = "Audio Track"
            if info:
                if 'entries' in info and len(info['entries']) > 0:
                    title = info['entries'][0].get('title', 'Audio Track')
                else:
                    title = info.get('title', 'Audio Track')

            pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_sc.*")
            for f in glob.glob(pattern):
                if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                    logging.info(f"✅ Yuklab olindi: {f}")
                    return f, title
    except Exception as e:
        logging.error(f"SoundCloud xatosi: {e}")

    return None, "Audio Track"


# ---------------------------------------------------------------------------
# MEDIA / VIDEO YUKLASH
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    return await asyncio.to_thread(_yt_dlp_download_video, url)


def _yt_dlp_download_video(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-6:]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")

    opts = {
        'format': 'best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
        'user_agent': USER_AGENT,
    }

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
