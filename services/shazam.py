import os
import logging
from shazamio import Shazam

async def recognize_audio(file_path: str) -> dict | None:
    """
    Shazamio orqali audio/video fayldan qo'shiqni aniqlash.
    """
    if not os.path.exists(file_path):
        logging.error(f"Shazam uchun fayl topilmadi: {file_path}")
        return None

    try:
        shazam = Shazam()
        out = await shazam.recognize(file_path)
        
        if not out or 'track' not in out:
            return None

        track = out['track']
        title = track.get('title', 'Noma\'lum')
        subtitle = track.get('subtitle', 'Noma\'lum ijrochi')
        
        # Qidiruv uchun kalit so'z
        query = f"{subtitle} - {title}"
        
        return {
            'title': title,
            'artist': subtitle,
            'query': query,
            'shazam_url': track.get('url', '')
        }
    except Exception as e:
        logging.error(f"Shazam aniqlashda xatolik: {e}")
        return None
