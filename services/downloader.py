import os
import shutil
import asyncio
import logging
import aiohttp
from ytmusicapi import YTMusic
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

# YTMusic ob'ekti (API Key va autentifikatsiyasiz ishlaydi)
ytmusic = YTMusic()

# Ishonchli va yangilangan public serverlar
FALLBACK_PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.mha.fi",
    "https://api.piped.yt"
]

FALLBACK_INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de"
]


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"


# ---------------------------------------------------------------------------
# QIDIRUV (YTMusic API -> Tezkor va Bloklanmaydi)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    search_query = query.strip()
    if not search_query:
        return []

    # 1. YTMusic orqali qidiruv (Eng ishonchli usul)
    def _ytmusic_search():
        try:
            results = ytmusic.search(search_query, filter="songs", limit=limit)
            tracks = []
            for item in results:
                v_id = item.get("videoId")
                if v_id:
                    artists = ", ".join([a['name'] for a in item.get('artists', [])])
                    tracks.append({
                        'id': v_id,
                        'title': item.get("title", "Unknown Track"),
                        'duration': item.get("duration", "0:00"),
                        'uploader': artists or "YouTube Music"
                    })
            return tracks
        except Exception as e:
            logging.error(f"YTMusic search error: {e}")
            return []

    tracks = await asyncio.to_thread(_ytmusic_search)
    if tracks:
        return tracks

    # 2. Zaxira: Piped / Invidious (Agar YTMusic da xatolik bo'lsa)
    connector = aiohttp.TCPConnector(ssl=False)
    headers = {"User-Agent": USER_AGENT}
    
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        for instance in FALLBACK_PIPED_INSTANCES:
            try:
                url = f"{instance}/search"
                params = {"q": search_query, "filter": "music_songs"}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = []
                        for entry in data.get("items", [])[:limit]:
                            v_id = entry.get("url", "").replace("/watch?v=", "")
                            if v_id:
                                results.append({
                                    'id': v_id,
                                    'title': entry.get("title", "Unknown"),
                                    'duration': format_duration(entry.get("duration", 0)),
                                    'uploader': entry.get("uploaderName", "YouTube")
                                })
                        if results:
                            return results
            except Exception:
                continue

    return []


# ---------------------------------------------------------------------------
# AUDIO YUKLASH (Cobalt API / Direct Stream)
# ---------------------------------------------------------------------------
async def _download_via_cobalt(video_id: str) -> str | None:
    target_url = f"https://www.youtube.com/watch?v={video_id}"
    payload = {
        "url": target_url,
        "downloadMode": "audio",
        "audioFormat": "mp3",
        "audioBitrate": "192"
    }
    connector = aiohttp.TCPConnector(ssl=False)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        # Cobalt rasmiy va zaxira API serverlari
        apis = ["https://api.cobalt.tools/api/json", "https://co.wuk.sh/api/json"]
        for api_url in apis:
            try:
                async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        stream_url = data.get("url")
                        if stream_url:
                            output_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
                            async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=30)) as s_resp:
                                if s_resp.status == 200:
                                    with open(output_path, "wb") as f:
                                        async for chunk in s_resp.content.iter_chunked(64 * 1024):
                                            f.write(chunk)
                                    if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                        return output_path
            except Exception:
                continue
    return None


async def _download_via_piped(video_id: str) -> str | None:
    connector = aiohttp.TCPConnector(ssl=False)
    headers = {"User-Agent": USER_AGENT}
    
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        for instance in FALLBACK_PIPED_INSTANCES:
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


async def download_audio_by_id(video_id_or_url: str, track_title: str = None, *args, **kwargs) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)
    if "v=" in youtube_id:
        youtube_id = youtube_id.split("v=")[1].split("&")[0]
    
    title_result = track_title or "Audio Track"

    # 1. Cobalt API orqali yuklash
    cobalt_path = await _download_via_cobalt(youtube_id)
    if cobalt_path:
        return cobalt_path, title_result, None

    # 2. Piped Stream orqali yuklash
    piped_path = await _download_via_piped(youtube_id)
    if piped_path:
        return piped_path, title_result, None

    return None, title_result, None


async def download_media(url: str) -> dict:
    return {"file_path": None, "title": "Video", "id": None}
