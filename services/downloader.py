import os
import glob
import shutil
import asyncio
import logging
import aiohttp
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file, save_to_cache

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
COOKIES_PATH = "cookies.txt"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# Ishonchli va ishlayotgan instansiyalar ro'yxati
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.mha.fi",
    "https://pipedapi.drgns.space",
    "https://api.piped.privacydev.net"
]

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.drgns.space",
    "https://vid.puffyan.us"
]

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

    # 1. Piped Stream Orqali (Tez va bloklanmaydi)
    if not youtube_id.startswith("http"):
        file_path, title = await _download_via_piped_direct(youtube_id, file_prefix)
        if file_path:
            return file_path, title, None

    # 2. Invidious Direct Audio Stream Orqali
    if not youtube_id.startswith("http"):
        file_path, title = await _download_via_invidious_direct(youtube_id, file_prefix)
        if file_path:
            return file_path, title, None

    # 3. Zaxiradagi yt-dlp (Ochiq formatlarda)
    file_path, title = await asyncio.to_thread(_yt_dlp_fallback_download, url, file_prefix)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None


async def _download_via_piped_direct(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    title = data.get("title", "Audio Track")
                    audio_streams = data.get("audioStreams", [])
                    if not audio_streams:
                        continue

                    # Eng yuqori sifatli audio streamni tanlaymiz
                    stream = audio_streams[0]
                    audio_url = stream.get("url")
                    ext = "m4a" if "mp4" in stream.get("mimeType", "") else "webm"
                    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.{ext}")

                    async with session.get(audio_url, timeout=aiohttp.ClientTimeout(total=40)) as stream_resp:
                        if stream_resp.status == 200:
                            with open(output_path, "wb") as f:
                                async for chunk in stream_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                logging.info(f"✅ Piped orqali audio yuklandi: {output_path}")
                                return output_path, title
            except Exception as e:
                logging.warning(f"Piped xatosi ({instance}): {e}")
                continue
    return None, "Audio Track"


async def _download_via_invidious_direct(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in INVIDIOUS_INSTANCES:
            try:
                url = f"{instance}/api/v1/videos/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    title = data.get("title", "Audio Track")
                    adaptive = data.get("adaptiveFormats", [])
                    
                    audios = [a for a in adaptive if "audio" in a.get("type", "")]
                    if not audios:
                        continue
                        
                    audio_url = audios[0].get("url")
                    ext = audios[0].get("container", "m4a")
                    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_inv.{ext}")

                    async with session.get(audio_url, timeout=aiohttp.ClientTimeout(total=40)) as stream_resp:
                        if stream_resp.status == 200:
                            with open(output_path, "wb") as f:
                                async for chunk in stream_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                logging.info(f"✅ Invidious orqali audio yuklandi: {output_path}")
                                return output_path, title
            except Exception as e:
                logging.warning(f"Invidious xatosi ({instance}): {e}")
                continue
    return None, "Audio Track"


def _yt_dlp_fallback_download(url: str, file_prefix: str) -> tuple[str | None, str]:
    output_tmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_ytdl.%(ext)s")
    opts = {
        'format': 'ba/ba*/b',
        'outtmpl': output_tmpl,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'user_agent': USER_AGENT,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb']
            }
        }
    }
    
    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Audio Track') if info else 'Audio Track'
            
        pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_ytdl.*")
        files = glob.glob(pattern)
        if files and os.path.getsize(files[0]) > 10240:
            return files[0], title
    except Exception as e:
        logging.error(f"yt-dlp zaxira xatosi: {e}")

    return None, "Audio Track"
