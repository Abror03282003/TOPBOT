import os
import logging
from typing import Optional
import yt_dlp

logger = logging.getLogger(__name__)

def setup_cookies() -> Optional[str]:
    """
    Railway Environment Variables tarkibidagi YOUTUBE_COOKIES
    matnidan vaqtinchalik cookies.txt faylini yaratadi.
    """
    cookies_content = os.environ.get("YOUTUBE_COOKIES")
    if cookies_content:
        cookie_path = "cookies.txt"
        with open(cookie_path, "w", encoding="utf-8") as f:
            f.write(cookies_content)
        return cookie_path
    return None

def download_youtube_audio(url: str, output_dir: str = "downloads") -> str:
    """
    YouTube'dan audioni eng yuqori sifatda yuklab oladi va fayl yo'lini qaytaradi.
    """
    os.makedirs(output_dir, exist_ok=True)
    cookie_file = setup_cookies()

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{output_dir}/%(id)s.%(ext)s',
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'quiet': True,
        'no_warnings': True,
        # 'web' client blokirovkasidan qutulish uchun mobile klientlar:
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'android', 'ios'],
                'player_skip': ['js', 'configs'],
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    # Cookie fayli mavjud bo'lsa sozlamaga qo'shamiz
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename
    except Exception as e:
        logger.error(f"yt-dlp orqali yuklashda xatolik yuz berdi: {e}")
        raise e
