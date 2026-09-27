import os
import glob
import shutil
import asyncio
import logging
import aiohttp
from pydub import AudioSegment

FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or shutil.which("ffmpeg") or "/usr/bin/ffprobe"

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    AudioSegment.converter = FFMPEG_PATH
if FFPROBE_PATH and os.path.exists(FFPROBE_PATH):
    AudioSegment.ffprobe = FFPROBE_PATH

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# Ishchi va tekshirilgan API instansiyalari
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.privacydev.net",
    "https://pipedapi.palvelu.org"
]


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"


# ---------------------------------------------------------------------------
# QIDIRUV (Piped API / YTMusic)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    search_query = query.strip()
    if not search_query:
        return []

    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/search"
                params = {"q": search_query, "filter": "music_songs"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = []
                        for entry in data.get("items", [])[:limit]:
                            item_id = entry.get("url", "").replace("/watch?v=", "")
                            if item_id:
                                results.append({
                                    'id': item_id,
                                    'title': entry.get("title", "Unknown"),
                                    'duration': format_duration(entry.get("duration", 0)),
                                    'uploader': entry.get("uploaderName", "YouTube Music")
                                })
                        if results:
                            return results
            except Exception as e:
                logging.warning(f"Piped qidiruv xatosi ({instance}): {e}")
                continue

    # Zaxira qidiruv (yt-dlp flat extract)
    return await asyncio.to_thread(_yt_search_fallback, search_query, limit)


def _yt_search_fallback(query: str, limit: int) -> list[dict]:
    import yt_dlp
    opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'user_agent': USER_AGENT,
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
                            'uploader': entry.get('uploader') or 'Artist'
                        })
            return items
    except Exception as e:
        logging.error(f"Fallback search xatosi: {e}")
        return []


# ---------------------------------------------------------------------------
# AUDIO YUKLASH (Cobalt / Piped Stream)
# ---------------------------------------------------------------------------
async def _download_via_piped(video_id: str) -> str | None:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    audio_streams = data.get("audioStreams", [])
                    if not audio_streams:
                        continue

                    stream_url = audio_streams[0].get("url")
                    ext = audio_streams[0].get("format", "m4a").lower()
                    raw_path = os.path.join(DOWNLOAD_DIR, f"{video_id}_raw.{ext}")

                    async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=30)) as s_resp:
                        if s_resp.status == 200:
                            with open(raw_path, "wb") as f:
                                async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                    f.write(chunk)

                            if os.path.exists(raw_path) and os.path.getsize(raw_path) > 10240:
                                mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
                                if FFMPEG_PATH:
                                    try:
                                        sound = AudioSegment.from_file(raw_path)
                                        sound.export(mp3_path, format="mp3", bitrate="192k")
                                        if os.path.exists(raw_path):
                                            os.remove(raw_path)
                                        return mp3_path
                                    except Exception:
                                        return raw_path
                                return raw_path
            except Exception:
                continue
    return None


async def _download_via_cobalt(video_id: str) -> str | None:
    target_url = f"https://www.youtube.com/watch?v={video_id}"
    payload = {
        "url": target_url,
        "downloadMode": "audio",
        "audioFormat": "mp3",
        "audioBitrate": "192"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.post("https://api.cobalt.tools/api/json", json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    stream_url = data.get("url")
                    if stream_url:
                        output_path = os.path.join(DOWNLOAD_DIR, f"cobalt_{video_id}.mp3")
                        async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=30)) as s_resp:
                            if s_resp.status == 200:
                                with open(output_path, "wb") as f:
                                    async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                        f.write(chunk)
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                    return output_path
        except Exception:
            pass
    return None


async def download_audio_by_id(video_id_or_url: str, track_title: str = None, *args, **kwargs) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)
    if "v=" in youtube_id:
        youtube_id = youtube_id.split("v=")[1].split("&")[0]
    
    title_result = track_title or "Audio Track"

    # 1. Piped Stream orqali yuklash (Fast Direct Stream)
    piped_path = await _download_via_piped(youtube_id)
    if piped_path:
        return piped_path, title_result, None

    # 2. Cobalt API zaxirasi
    cobalt_path = await _download_via_cobalt(youtube_id)
    if cobalt_path:
        return cobalt_path, title_result, None

    return None, title_result, None


async def download_media(url: str) -> dict:
    return {"file_path": None, "title": "Video", "id": None}
