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
        # YouTube Search (Asosiy va barqaror)
        try:
            yt_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
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

        # SoundCloud Search (Zaxira)
        try:
            sc_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
            with yt_dlp.YoutubeDL(sc_opts) as ydl:
                res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
                results = []
                if res and 'entries' in res and res['entries']:
                    for entry in res['entries']:
                        if entry:
                            url_or_id = entry.get('url') or entry.get('webpage_url') or entry.get('id')
                            results.append({
                                'id': url_or_id,
                                'title': entry.get('title', 'Unknown Title'),
                                'duration': format_duration(entry.get('duration', 0)),
                                'uploader': entry.get('uploader', 'SoundCloud')
                            })
                if results:
                    SEARCH_CACHE[clean_query] = results
                    return results
        except Exception as e:
            logging.error(f"SoundCloud search error: {e}")

        return []

    return await asyncio.to_thread(_search)


def _fetch_cobalt(target_url: str, out_file: str) -> bool:
    """Cobalt API orqali yuklash yordamchi funksiyasi"""
    try:
        logging.info(f"Cobalt API orqali yuklanmoqda: {target_url}")
        payload = {
            "url": target_url,
            "downloadMode": "audio",
            "audioFormat": "mp3"
        }
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        res = requests.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=12)
        data = res.json()

        download_url = data.get("url") if data.get("status") in ["tunnel", "redirect"] else None

        if download_url:
            r = requests.get(download_url, stream=True, timeout=30)
            if r.status_code == 200:
                with open(out_file, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                    logging.info(f"✅ Cobalt orqali muvaffaqiyatli yuklandi: {out_file}")
                    return True
    except Exception as e:
        logging.warning(f"Cobalt API yuklashda xatolik: {e}")
    return False


async def download_audio_by_id(video_id_or_url: str) -> tuple[str | None, str]:
    if str(video_id_or_url).startswith("http"):
        target_url = video_id_or_url
        file_prefix = "track_" + str(abs(hash(video_id_or_url)))[-8:]
    else:
        target_url = f"https://www.youtube.com/watch?v={video_id_or_url}"
        file_prefix = str(video_id_or_url)

    # 1. Keshni tekshirish
    pattern = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")
    files = glob.glob(pattern)
    for f in files:
        if os.path.getsize(f) > 10240 and not f.endswith(('.part', '.ytdl')):
            logging.info(f"Qo'shiq keshdan olindi: {f}")
            return f, "Audio Track"

    def _download():
        out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

        # 2-Bosqich: To'g'ridan-to'g'ri Cobalt orqali harakat qilish
        if _fetch_cobalt(target_url, out_file):
            return out_file, "Audio Track"

        # 3-Bosqich: yt-dlp bilan ma'lumot olish va yuklash
        track_title = "Audio Track"
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{DOWNLOAD_DIR}/{file_prefix}.%(ext)s',
                'quiet': True,
                'no_warnings': True,
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
                if info:
                    track_title = info.get('title', 'Audio Track')
                
                files = glob.glob(pattern)
                for f in files:
                    if os.path.getsize(f) > 10240 and not f.endswith(('.part', '.ytdl')):
                        return f, track_title
        except Exception as e:
            err_msg = str(e)
            logging.warning(f"Standart yuklashda xatolik: {err_msg}")

            # 4-Bosqich: AGAR SOUNDCLOUD DRM YOKI XATOLIK BO'LSA - YOUTUBE'DAN QIDIRISH
            if "DRM protected" in err_msg or "soundcloud" in target_url.lower():
                logging.info("SoundCloud DRM topildi. Qo'shiq YouTube orqali izlanmoqda...")
                try:
                    # Trek nomini metadata orqali olish
                    with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl_info:
                        meta = ydl_info.extract_info(target_url, download=False)
                        query_title = meta.get('title') if meta else None

                    if query_title:
                        # YouTube'dan qidiramiz
                        with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl_yt:
                            yt_res = ydl_yt.extract_info(f"ytsearch1:{query_title}", download=False)
                            if yt_res and 'entries' in yt_res and yt_res['entries']:
                                yt_id = yt_res['entries'][0]['id']
                                yt_url = f"https://www.youtube.com/watch?v={yt_id}"
                                
                                # Cobalt orqali yuklash
                                if _fetch_cobalt(yt_url, out_file):
                                    return out_file, query_title

                                # yt-dlp orqali yuklash
                                ydl_opts['outtmpl'] = f'{DOWNLOAD_DIR}/{file_prefix}.%(ext)s'
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl_final:
                                    ydl_final.extract_info(yt_url, download=True)
                                    files = glob.glob(pattern)
                                    for f in files:
                                        if os.path.getsize(f) > 10240:
                                            return f, query_title
                except Exception as fallback_err:
                    logging.error(f"YouTube Fallback xatosi: {fallback_err}")

        return None, track_title

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
        try:
            payload = {"url": url, "downloadMode": "auto"}
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            res = requests.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=15)
            data = res.json()
            
            if data.get("status") in ["tunnel", "redirect"]:
                v_url = data.get("url")
                r = requests.get(v_url, stream=True, timeout=60)
                v_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")
                with open(v_file, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                if os.path.exists(v_file) and os.path.getsize(v_file) > 10240:
                    return {"file_path": v_file, "title": "Video", "id": file_prefix}
        except Exception as e:
            logging.error(f"Video yuklash xatosi: {e}")

        return {"file_path": None, "title": "Video", "id": None}

    return await asyncio.to_thread(_download)
