import os
import shutil
import asyncio
import logging
from ytmusicapi import YTMusic
from yt_dlp import YoutubeDL

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

ytmusic = YTMusic()

# ---------------------------------------------------------------------------
# QIDIRUV (YTMusic API -> Instant & Reliable)
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
# AUDIO YUKLASH (yt-dlp Engine)
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None, *args, **kwargs) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)
    if "v=" in youtube_id:
        youtube_id = youtube_id.split("v=")[1].split("&")[0]

    video_url = f"https://www.youtube.com/watch?v={youtube_id}"
    output_template = os.path.join(DOWNLOAD_DIR, f"{youtube_id}.%(ext)s")
    expected_mp3_path = os.path.join(DOWNLOAD_DIR, f"{youtube_id}.mp3")

    # Agar fayl allaqachon yuklangan bo'lsa
    if os.path.exists(expected_mp3_path):
        return expected_mp3_path, track_title or "Audio Track", None

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'nocheckcertificate': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
    }

    def _yt_dlp_download():
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                title = info.get("title", track_title or "Audio Track")
                return expected_mp3_path, title
        except Exception as e:
            logging.error(f"yt-dlp download error: {e}")
            return None, track_title or "Audio Track"

    file_path, title = await asyncio.to_thread(_yt_dlp_download)

    if file_path and os.path.exists(file_path):
        return file_path, title, None

    return None, title, None


async def download_media(url: str) -> dict:
    return {"file_path": None, "title": "Video", "id": None}
