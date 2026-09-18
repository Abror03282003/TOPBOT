import os
import logging
from shazamio import Shazam

shazam = Shazam()

async def recognize_song(file_path: str) -> dict | None:
    """
    Har qanday media fayldan (mp3, ogg, mp4) musiqani aniqlab beradi.
    """
    if not os.path.exists(file_path):
        return None

    try:
        out = await shazam.recognize(file_path)
        track = out.get("track")
        if track:
            return {
                "title": track.get("title", "Noma'lum nom"),
                "artist": track.get("subtitle", "Noma'lum ijrochi"),
                "shazam_id": track.get("key"),
            }
    except Exception as e:
        logging.error(f"Shazam orqali aniqlashda xatolik: {e}")

    return None
