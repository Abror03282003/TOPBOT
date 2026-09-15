import os
import asyncio
import yt_dlp

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Common yt-dlp options
BASE_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
}

async def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """Qo'shiq nomiga ko'ra topilgan treklarni ro'yxat qilib qaytaradi."""
    ydl_opts = {
        **BASE_YDL_OPTS,
        'extract_flat': True,
        'default_search': f'ytsearch{limit}',
    }
    
    def _search():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            results = []
            if 'entries' in res:
                for entry in res['entries']:
                    results.append({
                        'id': entry.get('id'),
                        'title': entry.get('title', 'Unknown Title'),
                        'duration': entry.get('duration', 0),
                        'uploader': entry.get('uploader', 'Unknown Artist')
                    })
            return results

    return await asyncio.to_thread(_search)

async def download_audio_by_id(video_id_or_url: str) -> tuple[str, str]:
    """Video/Qo'shiq ID yoki URL bo'yicha MP3 yuklab beradi."""
    url = video_id_or_url if video_id_or_url.startswith("http") else f"https://www.youtube.com/watch?v={video_id_or_url}"
    
    ydl_opts = {
        **BASE_YDL_OPTS,
        'format': 'bestaudio/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Audio Track')
            file_id = info.get('id')
            file_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp3")
            return file_path, title

    return await asyncio.to_thread(_download)

async def download_media(url: str) -> dict:
    """Instagram yoki YouTube'dan videoni yuklab beradi."""
    ydl_opts = {
        **BASE_YDL_OPTS,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'max_filesize': 50 * 1024 * 1024, # Telegram limits (50MB)
    }

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return {
                "file_path": filename,
                "title": info.get("title", "Video"),
                "id": info.get("id")
            }

    return await asyncio.to_thread(_download)
