import os
import glob
import shutil
import asyncio
import logging
import aiohttp
import yt_dlp
from pydub import AudioSegment
from database import get_cached_file, save_to_cache

FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or shutil.which("ffmpeg") or "/usr/bin/ffprobe"

if not os.path.exists(FFMPEG_PATH):
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
        possible_ffprobe = os.path.join(ffmpeg_dir, "ffprobe")
        FFPROBE_PATH = possible_ffprobe if os.path.exists(possible_ffprobe) else FFMPEG_PATH
    except Exception as e:
        logging.warning(f"imageio_ffmpeg yuklashda ogohlantirish: {e}")

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    AudioSegment.converter = FFMPEG_PATH
if FFPROBE_PATH and os.path.exists(FFPROBE_PATH):
    AudioSegment.ffprobe = FFPROBE_PATH

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIES_PATH = "cookies.txt"

BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'geo_bypass': True,
    'cachedir': False,
}

if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
    BASE_YDL_OPTS['ffmpeg_location'] = FFMPEG_PATH


def _ensure_cookies_file():
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if cookies_env:
        try:
            with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                f.write(cookies_env.strip())
        except Exception as e:
            logging.error(f"Cookies faylini yozishda xatolik: {e}")


def _get_active_opts(extra_opts: dict) -> dict:
    _ensure_cookies_file()
    opts = {**BASE_YDL_OPTS, **extra_opts}
    if os.path.exists(COOKIES_PATH) and os.path.getsize(COOKIES_PATH) > 0:
        opts['cookiefile'] = COOKIES_PATH
    return opts


def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


async def search_tracks(query: str, limit: int = 30) -> list[dict]:
    # 1. Piped API orqali qidiruv (YouTube bloklarini aylanib o'tadi)
    piped_instances = [
        "https://pipedapi.kavin.rocks",
        "https://api.piped.privacydev.net",
        "https://pipedapi.mha.fi"
    ]
    async with aiohttp.ClientSession() as session:
        for instance in piped_instances:
            try:
                url = f"{instance}/search?q={aiohttp.helpers.quote(query)}&filter=music_songs"
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("items", [])
                        results = []
                        for item in items[:limit]:
                            yt_id = item.get("url", "").replace("/watch?v=", "")
                            if yt_id:
                                results.append({
                                    'id': yt_id,
                                    'title': item.get('title', 'Unknown Title'),
                                    'duration': format_duration(item.get('duration', 0)),
                                    'uploader': item.get('uploaderName', 'Unknown Artist')
                                })
                        if results:
                            return results
            except Exception:
                continue

    # 2. yt-dlp orqali zaxira qidiruvi
    def _yt_dlp_search():
        try:
            opts = _get_active_opts({
                'extract_flat': True,
                'skip_download': True,
                'extractor_args': {'youtube': {'player_client': ['ios', 'android']}}
            })
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                if res and 'entries' in res and res['entries']:
                    return [
                        {
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Unknown Title'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader', 'Unknown Artist')
                        }
                        for entry in res['entries'] if entry and entry.get('id')
                    ]
        except Exception as e:
            logging.error(f"YouTube search error: {e}")
        return []

    return await asyncio.to_thread(_yt_dlp_search)


async def _download_via_external_api(video_id: str, file_prefix: str) -> tuple[str | None, str]:
    """Cobalt va Piped orqali YouTube blokirovkalarini 100% chetlab o'tib audioni yuklash."""
    target_url = f"https://www.youtube.com/watch?v={video_id}"
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    # 1. Ishonchli Cobalt API tugunlari
    cobalt_instances = [
        "https://api.cobalt.tools",
        "https://cobalt.api.scouts.org.ua",
        "https://co.wuk.sh"
    ]
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    payload = {"url": target_url, "downloadMode": "audio", "audioFormat": "mp3"}

    async with aiohttp.ClientSession() as session:
        for instance in cobalt_instances:
            try:
                async with session.post(f"{instance}/", json=payload, headers=headers, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        dl_url = data.get("url")
                        if dl_url:
                            async with session.get(dl_url) as f_resp:
                                if f_resp.status == 200:
                                    with open(output_path, "wb") as f:
                                        f.write(await f_resp.read())
                                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                        return output_path, "Audio Track"
            except Exception as e:
                logging.warning(f"Cobalt instance ({instance}) xatosi: {e}")

        # 2. Piped Stream API tugunlari (Zaxira)
        piped_instances = [
            "https://pipedapi.kavin.rocks",
            "https://api.piped.privacydev.net"
        ]
        for p_instance in piped_instances:
            try:
                async with session.get(f"{p_instance}/streams/{video_id}", timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        title = data.get("title", "Audio Track")
                        audio_streams = data.get("audioStreams", [])
                        if audio_streams:
                            stream_url = audio_streams[0].get("url")
                            async with session.get(stream_url) as f_resp:
                                if f_resp.status == 200:
                                    with open(output_path, "wb") as f:
                                        f.write(await f_resp.read())
                                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                        return output_path, title
            except Exception as e:
                logging.warning(f"Piped instance ({p_instance}) xatosi: {e}")

    return None, "Audio Track"


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str, str | None]:
    youtube_id = str(video_id_or_url)

    cached_file_id = await get_cached_file(youtube_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    file_prefix = "sc_" + str(abs(hash(video_id_or_url)))[-6:] if str(video_id_or_url).startswith("http") else str(video_id_or_url)

    # 1-qadam: Avval API orqali tez va blokirovkasiz yuklab olishga urinish
    if not str(video_id_or_url).startswith("http"):
        api_file, track_title = await _download_via_external_api(youtube_id, file_prefix)
        if api_file and os.path.exists(api_file):
            return api_file, track_title, None

    # 2-qadam: yt-dlp orqali mahalliy yuklab olish
    url = video_id_or_url if str(video_id_or_url).startswith("http") else f"https://www.youtube.com/watch?v={video_id_or_url}"

    def _download():
        title = "Audio Track"
        pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
        clients = [['ios'], ['android_vr'], ['tv_embedded'], ['mweb']]

        for client in clients:
            ydl_opts = _get_active_opts({
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_prefix}.%(ext)s'),
                'extractor_args': {'youtube': {'player_client': client, 'skip': ['webpage']}}
            })
            if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        title = info.get('title', 'Audio Track')

                files = [f for f in glob.glob(pattern) if not f.endswith(('.part', '.ytdl'))]
                for f in files:
                    if os.path.exists(f) and os.path.getsize(f) > 0:
                        return f, title, None
            except Exception:
                continue

        return None, title, None

    return await asyncio.to_thread(_download)


async def download_media(url: str) -> dict:
    def _download():
        clients = [['ios'], ['android_vr'], ['tv_embedded'], ['mweb']]
        for client in clients:
            ydl_opts = _get_active_opts({
                'format': 'bestvideo+bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s.%(ext)s'),
                'max_filesize': 50 * 1024 * 1024,
                'merge_output_format': 'mp4',
                'extractor_args': {'youtube': {'player_client': client, 'skip': ['webpage']}}
            })
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        filename = ydl.prepare_filename(info)
                        base, _ = os.path.splitext(filename)
                        if os.path.exists(f"{base}.mp4"):
                            filename = f"{base}.mp4"
                        if os.path.exists(filename) and os.path.getsize(filename) > 0:
                            return {"file_path": filename, "title": info.get("title", "Video"), "id": info.get("id")}
            except Exception:
                continue
        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
