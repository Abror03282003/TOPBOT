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

ytmusic = YTMusic()

# Ishonchli va yangi audio-proxy serverlar ro'yxati
AUDIO_PROXY_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://pipedapi.kavin.rocks",
    "https://api.piped.yt"
]


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"


# ---------------------------------------------------------------------------
# QIDIRUV (YTMusic)
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    search_query = query.strip()
    if not search_query:
        return []

    def _ytmusic_search():
        try:
            results = ytmusic.search(search_query, filter="songs", limit=limit)
            tracks = []
            for item in results:
                v_id = item.get("videoId")
                if v_id:
                    artists = ", ".join([a['name'] for a in item.get('artists', []) if 'name' in a])
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

    return await asyncio.to_thread(_ytmusic_search)


# ---------------------------------------------------------------------------
# AUDIO YUKLASH (Multi-source Stream Downloader)
# ---------------------------------------------------------------------------

async def _download_from_invidious_proxy(video_id: str) -> str | None:
    """Invidious va Piped serverlaridan audio oqimni yuklab olish"""
    connector = aiohttp.TCPConnector(ssl=False)
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        for instance in AUDIO_PROXY_INSTANCES:
            try:
                # 1-Urinish: Invidious API
                if "inv" in instance or "invidious" in instance:
                    url = f"{instance}/api/v1/videos/{video_id}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            adaptive = data.get("adaptiveFormats", [])
                            audio_streams = [f for f in adaptive if "audio" in f.get("type", "")]
                            if audio_streams:
                                stream_url = audio_streams[0].get("url")
                                ext = audio_streams[0].get("container", "m4a").lower()
                                path = await _stream_to_file(session, stream_url, video_id, ext)
                                if path:
                                    return path

                # 2-Urinish: Piped API
                elif "piped" in instance:
                    url = f"{instance}/streams/{video_id}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            audio_streams = data.get("audioStreams", [])
                            if audio_streams:
                                stream_url = audio_streams[0].get("url")
                                ext = audio_streams[0].get("format", "m4a").lower()
                                path = await _stream_to_file(session, stream_url, video_id, ext)
                                if path:
                                    return path
            except Exception as e:
                logging.warning(f"Download stream fail ({instance}): {e}")
                continue
    return None


async def _download_from_cobalt_public(video_id: str) -> str | None:
    """Cobalt API orqali MP3 ga o'girilgan holda olish"""
    target_url = f"https://www.youtube.com/watch?v={video_id}"
    payload = {
        "url": target_url,
        "downloadMode": "audio",
        "audioFormat": "mp3"
    }
    connector = aiohttp.TCPConnector(ssl=False)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        endpoints = [
            "https://api.cobalt.tools/api/json",
            "https://cobalt-api.kwiatek.xyz/api/json"
        ]
        for api in endpoints:
            try:
                async with session.post(api, json=payload, timeout=aiohttp.ClientTimeout(total=7)) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        stream_url = data.get("url")
                        if stream_url:
                            path = await _stream_to_file(session, stream_url, video_id, "mp3")
                            if path:
                                return path
            except Exception:
                continue
    return None


async def _stream_to_file(session: aiohttp.ClientSession, url: str, video_id: str, ext: str) -> str | None:
    """Oqimni (stream) mahalliy xotiraga saqlash va FFmpeg orqali MP3 qilish"""
    raw_path = os.path.join(DOWNLOAD_DIR, f"{video_id}_temp.{ext}")
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
            if resp.status == 200:
                with open(raw_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        f.write(chunk)

                if os.path.exists(raw_path) and os.path.getsize(raw_path) > 10240:
                    mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
                    if FFMPEG_PATH:
                        try:
                            def _convert():
                                sound = AudioSegment.from_file(raw_path)
                                sound.export(mp3_path, format="mp3", bitrate="192k")
                                if os.path.exists(raw_path):
                                    os.remove(raw_path)
                                return mp3_path
                            return await asyncio.to_thread(_convert)
                        except Exception as e:
                            logging.error(f"FFmpeg conversion error: {e}")
                            return raw_path
                    return raw_path
    except Exception as e:
        logging.error(f"Stream saving error: {e}")
        if os.path.exists(raw_path):
            os.remove(raw_path)
    return None


async def download_audio_by_id(video_id_or_url: str, track_title: str = None, *args, **kwargs) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)
    if "v=" in youtube_id:
        youtube_id = youtube_id.split("v=")[1].split("&")[0]

    title_result = track_title or "Audio Track"

    # 1-Baskich: Invidious / Piped Audio Stream
    file_path = await _download_from_invidious_proxy(youtube_id)
    if file_path:
        return file_path, title_result, None

    # 2-Bosqich: Cobalt MP3 Exporter
    file_path = await _download_from_cobalt_public(youtube_id)
    if file_path:
        return file_path, title_result, None

    return None, title_result, None


async def download_media(url: str) -> dict:
    return {"file_path": None, "title": "Video", "id": None}
