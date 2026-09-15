import os
import logging
from shazamio import Shazam

shazam = Shazam()

async def recognize_audio(file_path: str) -> dict | None:
    """Fayldan (audio/voice/video_note) qo'shiqni tanib oladi."""
    try:
        # Shazam orqali audio namunasini tahlil qilamiz
        out = await shazam.recognize(file_path)
        track = out.get('track')
        if track:
            return {
                'title': track.get('title'),
                'subtitle': track.get('subtitle'), # Xonanda nomi
                'full_title': f"{track.get('subtitle')} - {track.get('title')}"
            }
    except Exception as e:
        logging.error(f"Shazam bilan ishlashda xatolik: {e}")
    return None
