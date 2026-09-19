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
# 1. FFmpeg va Muhit Sozlamalari
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

# Ishlaydigan Piped API misollari (YouTube blokirovkasidan xoli)
PIPED_APIS = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.mha.fi",
    "https://api.piped.yt",
    "https://pipedapi.drgns.space",
    "https://pipedapi.adminforge.de"
]

def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        minutes = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{minutes}:{secs:02d}"
    except Exception:
        return "0:00"

# ---------------------------------------------------------------------------
# 2. QIDIRUV (Piped API orqali YouTube bazasidan topadi)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    search_query = query.strip()
    if not search_query:
        return []
    
    # 1-darajali: Piped API orqali tezkor va blokirovkasiz qidiruv
    results = await _search_piped(search_query, limit)
    if results:
        logging.info(f"✅ Qidiruv muvaffaqiyatli (Piped): '{search_query}' bo'yicha {len(results)} ta natija.")
        return results

    # 2-darajali: yt-dlp flat search (zaxira)
    return await asyncio.to_thread(_yt_flat_search, search_query, limit)

async def _search_piped(query: str, limit: int) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for api in PIPED_APIS:
            try:
                url = f"{api}/search"
                params = {"q": query, "filter": "music_songs"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = []
                        for entry in data.get("items", [])[:limit]:
                            v_id = entry.get("url", "").replace("/watch?v=", "")
                            if v_id:
                                items.append({
                                    'id': v_id,
                                    'title': entry.get("title", "Unknown"),
                                    'duration': format_duration(entry.get("duration", 0)),
                                    'uploader': entry.get("uploaderName", "Music")
                                })
                        if items:
                            return items
            except Exception:
                continue
    return []

def _yt_flat_search(query: str, limit: int) -> list[dict]:
    opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'user_agent': USER_AGENT
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry and entry.get('id'):
                        items.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Unknown Track'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader') or 'Music'
                        })
            return items
    except Exception:
        return []

# ---------------------------------------------------------------------------
# 3. AUDIO YUKLASH (IP Blokirovkasiz Piped Stream orqali)
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)

    # Keshda bor-yo'qligini tekshirish
    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if track_id.startswith("http"):
        if "v=" in track_id:
            v_id = track_id.split("v=")[1].split("&")[0]
        else:
            v_id = track_id.split("/")[-1]
    else:
        v_id = track_id

    file_prefix = f"audio_{v_id}"

    # Audioni yuklab olish
    file_path, title = await _download_piped_stream(v_id, file_prefix)
    if file_path:
        return file_path, title, None

    return None, "Audio Track", None

async def _download_piped_stream(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for api in PIPED_APIS:
            try:
                url = f"{api}/streams/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    title = data.get("title", "Audio Track")
                    audio_streams = data.get("audioStreams", [])
                    
                    if not audio_streams:
                        continue

                    # Eng sifatli oqimni tanlaymiz
                    audio_streams.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
                    stream_url = audio_streams[0].get("url")
                    mime = audio_streams[0].get("mimeType", "")
                    ext = "m4a" if "m4a" in mime or "mp4" in mime else "webm"
                    
                    raw_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}_raw.{ext}")
                    mp3_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

                    # Faylni yuklab olish
                    async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=30)) as s_resp:
                        if s_resp.status == 200:
                            with open(raw_path, "wb") as f:
                                async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)
                            
                            if os.path.exists(raw_path) and os.path.getsize(raw_path) > 10240:
                                if FFMPEG_PATH:
                                    sound = AudioSegment.from_file(raw_path)
                                    sound.export(mp3_path, format="mp3", bitrate="192k")
                                    if os.path.exists(raw_path):
                                        os.remove(raw_path)
                                    logging.info(f"✅ Audio muvaffaqiyatli yuklandi: {mp3_path}")
                                    return mp3_path, title
                                else:
                                    return raw_path, title
            except Exception as e:
                logging.warning(f"Piped server ({api}) xatosi: {e}")
                continue
    return None, "Audio Track"

# ---------------------------------------------------------------------------
# 4. IJTIMOIY TARMOQLARDAN VIDEO YUKLASH (Instagram, TikTok, YouTube va h.k)
# ---------------------------------------------------------------------------
async def download_media(url: str) -> dict:
    return await asyncio.to_thread(_download_social_video, url.strip())

def _download_social_video(url: str) -> dict:
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s")

    opts = {
        'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
        'outtmpl': outtmpl,
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
        'user_agent': USER_AGENT
    }

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
        logging.error(f"Video yuklashda xatolik: {e}")

    return {"file_path": None, "title": "Video", "id": None}
