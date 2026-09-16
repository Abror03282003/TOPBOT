import os
import asyncio
import subprocess
from shazamio import Shazam

async def identify_track(input_file_path: str) -> str | None:
    """
    Ixtiyoriy media fayldan (video, voice, audio note) 
    12 soniyalik parcha kesib olib, Shazam orqali qo'shiqni aniqlaydi.
    """
    sample_wav = f"{input_file_path}_sample.wav"
    
    try:
        # FFmpeg orqali 2-soniyadan boshlab 12 soniyalik Mono/44.1kHz WAV tayyorlash
        cmd = [
            "ffmpeg", "-y",
            "-ss", "00:00:02",
            "-i", input_file_path,
            "-t", "12",
            "-vn",
            "-ac", "1",
            "-ar", "44100",
            "-f", "wav",
            sample_wav
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        await proc.communicate()

        # Agar fayl 2 soniyadan qisqa bo'lsa, faylni boshidan kesib olamiz
        if not os.path.exists(sample_wav) or os.path.getsize(sample_wav) == 0:
            cmd_fallback = [
                "ffmpeg", "-y",
                "-i", input_file_path,
                "-t", "12",
                "-vn",
                "-ac", "1",
                "-ar", "44100",
                "-f", "wav",
                sample_wav
            ]
            proc_fb = await asyncio.create_subprocess_exec(
                *cmd_fallback,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await proc_fb.communicate()

        if not os.path.exists(sample_wav) or os.path.getsize(sample_wav) == 0:
            return None

        # Shazam'ga yuborish
        shazam = Shazam()
        out = await shazam.recognize(sample_wav)
        
        track = out.get('track')
        if track:
            title = track.get('title', '')
            subtitle = track.get('subtitle', '')
            return f"{subtitle} - {title}".strip(" -")
            
        return None

    except Exception as e:
        print(f"Shazam error: {e}")
        return None
    finally:
        if os.path.exists(sample_wav):
            os.remove(sample_wav)
