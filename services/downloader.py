import os
import re
import time
import glob
import shutil
import asyncio
import logging
import aiohttp
import yt_dlp
from urllib.parse import urlparse, parse_qs
from pydub import AudioSegment
from database import get_cached_file

__all__ = ["search_tracks", "download_audio_by_id", "download_media"]

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# FFMPEG VA FFPROBE TEKSHIRUVI
# ---------------------------------------------------------------------------
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

if not FFPROBE_PATH and FFMPEG_PATH:
    candidate = os.path.join(os.path.dirname(FFMPEG_PATH), "ffprobe")
    FFPROBE_PATH = candidate if os.path.exists(candidate) else FFMPEG_PATH

if FFMPEG_PATH:
    AudioSegment.converter = FFMPEG_PATH
if FFPROBE_PATH:
    AudioSegment.ffprobe = FFPROBE_PATH

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# COOKIES SOZLAMASI
# ---------------------------------------------------------------------------
COOKIES_FILE = os.path.join(DOWNLOAD_DIR, "cookies.txt")
raw_cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()


def _validate_cookie_format(text: str) -> bool:
    """yt-dlp faqat Netscape HTTP Cookie File formatini tushunadi.
    Boshqa formatdagi (masalan JSON yoki brauzer eksport qilgan boshqa
    ko'rinishdagi) matn jimgina e'tiborsiz qoldiriladi va bot cookie'siz
    ishlayotgandek xatolikka uchraydi. Shu yerda erta tekshiramiz."""
    if not text:
        return False
    first_line = text.strip().splitlines()[0].strip() if text.strip() else ""
    if first_line.startswith("# Netscape HTTP Cookie File") or first_line.startswith("# HTTP Cookie File"):
        return True
    # Ba'zan eksport vositalari sarlavha izohini qo'shmaydi, lekin qatorlar
    # tab bilan ajratilgan 7 ustunli bo'lishi kerak (Netscape formati).
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if len(line.split("\t")) == 7:
            return True
        break
    return False


if raw_cookies:
    if _validate_cookie_format(raw_cookies):
        try:
            with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                if not raw_cookies.startswith("# Netscape") and not raw_cookies.startswith("# HTTP"):
                    f.write("# Netscape HTTP Cookie File\n")
                f.write(raw_cookies)
            logging.info("✅ YouTube cookies.txt fayli yaratildi (format to'g'ri).")
        except Exception as e:
            logging.error(f"Cookies faylini yozishda xatolik: {e}")
            COOKIES_FILE = None
    else:
        logging.error(
            "❌ YOUTUBE_COOKIES formati noto'g'ri! yt-dlp faqat Netscape "
            "HTTP Cookie File formatini qabul qiladi (birinchi qatori "
            "'# Netscape HTTP Cookie File' bo'lishi kerak, qatorlar TAB "
            "bilan ajratilgan 7 ustundan iborat bo'lishi kerak). Brauzer "
            "kengaytmasi 'Get cookies.txt LOCALLY' orqali qaytadan eksport "
            "qiling. Cookie ishlatilmaydi."
        )
        COOKIES_FILE = None
else:
    COOKIES_FILE = None
    logging.warning("⚠️ YOUTUBE_COOKIES o'rnatilmagan — bot cookie'siz ishlaydi, bloklanish ehtimoli yuqori.")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# ---------------------------------------------------------------------------
# PO TOKEN PROVIDER (bgutil-ytdlp-pot-provider HTTP server)
# ---------------------------------------------------------------------------
# Railway konteynerining o'zida Node/Deno ishlamasligi mumkin (nixpacks
# nix-paketlarni har doim runtime image'ga to'liq o'tkazmaydi), shuning
# uchun PO Token generatsiya qiluvchi server ALOHIDA xizmat sifatida
# (masalan brainicism/bgutil-ytdlp-pot-provider Docker image'i) ishga
# tushiriladi. Shu xizmatning ichki (Railway private network) manzilini
# POT_PROVIDER_URL environment variable orqali beramiz.
POT_PROVIDER_URL = os.environ.get("POT_PROVIDER_URL", "").strip().rstrip("/")
if POT_PROVIDER_URL:
    logging.info(f"✅ PO Token provider ulandi: {POT_PROVIDER_URL}")
else:
    logging.warning(
        "⚠️ POT_PROVIDER_URL o'rnatilmagan — PO Token generatsiya qilinmaydi, "
        "YouTube ko'p hollarda 'Sign in to confirm you're not a bot' bilan "
        "bloklashi mumkin. Alohida bgutil-ytdlp-pot-provider xizmatini "
        "o'rnatib, uning manzilini shu o'zgaruvchiga bering."
    )


def _pot_extractor_args() -> dict:
    """POT_PROVIDER_URL berilgan bo'lsa, yt-dlp'ning youtube extractor_args
    ichiga bgutil HTTP provider manzilini qo'shadi."""
    if not POT_PROVIDER_URL:
        return {}
    return {'youtubepot-bgutilhttp': {'base_url': [POT_PROVIDER_URL]}}


def _build_youtube_extractor_args(clients: list | None) -> dict:
    """'youtube' (player_client) va PO Token ('youtubepot-bgutilhttp')
    argumentlarini bitta joyda, to'g'ri (aka-uka kalitlar sifatida)
    birlashtiradigan yordamchi funksiya — audio va video yuklash
    funksiyalarida takrorlanmasligi uchun."""
    args = dict(_pot_extractor_args())
    if clients:
        args['youtube'] = {
            'player_client': clients,
            'player_skip': ['js', 'configs', 'webpage'],
        }
    return args


class _PotDiagLogger:
    """yt-dlp'ning debug chiqishidan faqat PO Token va JS Challenge
    provider qatorlarini ushlab, oddiy logging orqali ko'rsatadi. Bu
    bo'lmasa, bgutil-ytdlp-pot-provider haqiqatda ishlayaptimi yoki yo'qligini
    bilishning iloji yo'q edi (build muvaffaqiyatsiz bo'lsa ham jim
    o'tib ketardi)."""

    def debug(self, msg):
        if '[pot]' in msg or '[jsc]' in msg or 'PO Token' in msg or 'JS Challenge' in msg:
            logging.info(f"🔎 DIAGNOSTIKA: {msg.strip()}")

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def log_pot_diagnostics():
    """Bot ishga tushganda BIR MARTA chaqiriladi: PO Token/JS Challenge
    provider'lar haqiqatda topilganmi-yo'qmi, buni loglarga chiqaradi.
    Agar 'PO Token Providers: none' ko'rinsa — bgutil plagin ishlamayapti,
    demak build bosqichidagi npm/npx buyruqlari muvaffaqiyatsiz bo'lgan."""
    try:
        opts = {
            'quiet': True,
            'no_warnings': False,
            'verbose': True,
            'simulate': True,
            'skip_download': True,
            'logger': _PotDiagLogger(),
            'extractor_args': _build_youtube_extractor_args(['mweb']),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info("https://www.youtube.com/watch?v=jNQXAC9IVRw", download=False)
    except Exception as e:
        logging.info(f"🔎 DIAGNOSTIKA: tekshiruvda xatolik (bu normal bo'lishi mumkin): {e}")

# ---------------------------------------------------------------------------
# PIPED / INVIDIOUS INSTANCE RO'YXATI (dinamik yangilanadi)
# ---------------------------------------------------------------------------
# Bular faqat "urug'" (seed) ro'yxat — startdan keyin _refresh_instances()
# haqiqiy tirik instance ro'yxatini olishga harakat qiladi. Agar internetdan
# olib bo'lmasa, shu statik ro'yxat zaxira sifatida ishlatiladi.
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi-libre.kavin.rocks",
    "https://piped-api.lunar.icu",
    "https://api.piped.yt",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.leptons.xyz",
]

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://iv.melmac.space",
    "https://invidious.jing.rocks",
    "https://invidious.f5.si",
    "https://yewtu.be",
]

_INSTANCES_LAST_REFRESH = 0
_INSTANCE_REFRESH_INTERVAL = 6 * 60 * 60  # 6 soatda bir marta yangilash
_instance_lock = asyncio.Lock()


async def _refresh_instances() -> None:
    """Piped/Invidious instance ro'yxatini jonli manbadan yangilaydi.
    Ishlamasa, mavjud (statik) ro'yxat o'z holicha qoladi — bot hech qachon
    bu tufayli to'xtab qolmaydi."""
    global PIPED_INSTANCES, INVIDIOUS_INSTANCES, _INSTANCES_LAST_REFRESH

    now = time.time()
    if now - _INSTANCES_LAST_REFRESH < _INSTANCE_REFRESH_INTERVAL:
        return

    async with _instance_lock:
        if now - _INSTANCES_LAST_REFRESH < _INSTANCE_REFRESH_INTERVAL:
            return

        new_invidious = []
        new_piped = []

        try:
            async with get_session() as session:
                async with session.get(
                    "https://api.invidious.io/instances.json?sort_by=type,health",
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for _, info in data:
                            if info.get("type") == "https" and info.get("api"):
                                uri = info.get("uri", "").rstrip("/")
                                if uri:
                                    new_invidious.append(uri)
        except Exception as e:
            logging.warning(f"Invidious instance ro'yxatini yangilab bo'lmadi: {e}")

        try:
            async with get_session() as session:
                async with session.get(
                    "https://piped-instances.kavin.rocks/",
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for info in data:
                            api_url = info.get("api_url", "").rstrip("/")
                            if api_url:
                                new_piped.append(api_url)
        except Exception as e:
            logging.warning(f"Piped instance ro'yxatini yangilab bo'lmadi: {e}")

        if new_invidious:
            INVIDIOUS_INSTANCES = new_invidious[:8] + INVIDIOUS_INSTANCES
            INVIDIOUS_INSTANCES = list(dict.fromkeys(INVIDIOUS_INSTANCES))  # dublikatlarni olib tashlash
            logging.info(f"✅ {len(new_invidious)} ta Invidious instance topildi.")

        if new_piped:
            PIPED_INSTANCES = new_piped[:8] + PIPED_INSTANCES
            PIPED_INSTANCES = list(dict.fromkeys(PIPED_INSTANCES))
            logging.info(f"✅ {len(new_piped)} ta Piped instance topildi.")

        _INSTANCES_LAST_REFRESH = now


COBALT_API_KEY = os.environ.get("COBALT_API_KEY", "").strip()
# Kalit bo'lmasa ham ba'zi ochiq Cobalt instance'lar ishlaydi (limitli);
# shuning uchun ro'yxatni butunlay bo'shatib qo'ymaymiz.
COBALT_INSTANCES = ["https://api.cobalt.tools"]
if not COBALT_API_KEY:
    logging.warning(
        "⚠️ COBALT_API_KEY o'rnatilmagan — cobalt.tools so'rovlari "
        "cheklangan/ishlamasligi mumkin. https://cobalt.tools dan yoki "
        "o'zingiz self-host qilgan instance'dan kalit oling."
    )


_VIDEO_ID_RE = re.compile(
    r'(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/|live/))([A-Za-z0-9_-]{11})'
)


def _extract_video_id(url: str) -> str:
    """youtu.be, /shorts/, /embed/, ?si= kabi barcha YouTube havola
    ko'rinishlaridan video ID'ni ishonchli ajratib oladi. Eski kod faqat
    'v=' yoki oxirgi '/' bo'lagini olardi va query-parametrlarni
    (masalan '?si=...') ID'ga qo'shib yuborardi."""
    match = _VIDEO_ID_RE.search(url)
    if match:
        return match.group(1)
    parsed = urlparse(url)
    qs_id = parse_qs(parsed.query).get("v")
    if qs_id:
        return qs_id[0]
    return parsed.path.rstrip("/").split("/")[-1]


def format_duration(seconds) -> str:
    if not seconds:
        return "0:00"
    try:
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
    except Exception:
        return "0:00"


def get_session():
    connector = aiohttp.TCPConnector(ssl=False)
    return aiohttp.ClientSession(connector=connector, headers={"User-Agent": USER_AGENT})


# ---------------------------------------------------------------------------
# QIDIRUV FUNKSIYALARI
# ---------------------------------------------------------------------------
async def search_tracks(query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []

    results = await asyncio.to_thread(_search_ytdlp_sync, query, limit)
    if results:
        return results

    return await asyncio.to_thread(_search_soundcloud_sync, query, limit)


def _search_ytdlp_sync(query: str, limit: int) -> list[dict]:
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'extractor_args': {
                'youtube': {
                    # mobil client'lar odatda web-cookie'siz ham ishlaydi va
                    # bot-tekshiruviga kamroq uchraydi
                    'player_client': ['ios', 'android', 'mweb'],
                },
                **_pot_extractor_args(),
            }
        }
        # ^ e'tibor bering: PO Token argumenti 'youtube' kalitining ICHIGA
        # emas, extractor_args'ning yuqori darajasiga (aka-uka kalit
        # sifatida) qo'shiladi — chunki 'youtubepot-bgutilhttp' alohida
        # extractor sifatida ishlaydi.
        # Qidiruvda cookie shart emas va mobil client bilan aralashib,
        # ziddiyat keltirib chiqarishi mumkin — shu sabab bu yerda ishlatilmaydi.

        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if entry and entry.get('id'):
                        items.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Unknown Track'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader') or entry.get('channel') or 'YouTube'
                        })
            if items:
                logging.info(f"✅ yt-dlp orqali {len(items)} ta qo'shiq topildi.")
                return items
    except Exception as e:
        logging.warning(f"yt-dlp search xatosi: {e}")
    return []


def _search_soundcloud_sync(query: str, limit: int) -> list[dict]:
    try:
        opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            items = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    webpage_url = entry.get('webpage_url') or entry.get('url')
                    if webpage_url:
                        items.append({
                            'id': webpage_url,
                            'title': entry.get('title', 'Unknown Track'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'uploader': entry.get('uploader') or 'SoundCloud',
                        })
            if items:
                logging.info(f"✅ SoundCloud orqali {len(items)} ta qo'shiq topildi.")
                return items
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# YUKLASH FUNKSIYALARI
# ---------------------------------------------------------------------------
async def download_audio_by_id(video_id_or_url: str, track_title: str = None) -> tuple[str | None, str, str | None]:
    track_id = str(video_id_or_url)

    cached_file_id = await get_cached_file(track_id)
    if cached_file_id:
        return None, "Audio Track", cached_file_id

    if not track_id.startswith("http://") and not track_id.startswith("https://"):
        target_url = f"https://www.youtube.com/watch?v={track_id}"
        video_id = track_id
        file_prefix = f"audio_{track_id}"
    else:
        target_url = track_id
        video_id = _extract_video_id(track_id)
        file_prefix = f"audio_{abs(hash(track_id))}"

    out_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp3")

    # Instance ro'yxatini fon rejimida yangilashga urinib ko'ramiz (bloklamaydi)
    try:
        await asyncio.wait_for(_refresh_instances(), timeout=10)
    except Exception:
        pass

    # 1-Bosqich: yt-dlp client spoofing
    logging.info(f"🚀 yt-dlp client orqali yuklanmoqda: {target_url}")
    file_path, title = await asyncio.to_thread(_download_ytdlp_client_sync, target_url, file_prefix, track_title)
    if file_path:
        return file_path, title, None

    # 2-Bosqich: Piped API
    logging.info(f"🚀 Piped API orqali yuklanmoqda: {video_id}")
    file_path = await _download_via_piped(video_id, out_file)
    if file_path:
        return file_path, track_title or "Audio Track", None

    # 3-Bosqich: Invidious API
    logging.info(f"🚀 Invidious API orqali yuklanmoqda: {video_id}")
    file_path = await _download_via_invidious(video_id, out_file)
    if file_path:
        return file_path, track_title or "Audio Track", None

    # 4-Bosqich: Cobalt API
    if COBALT_INSTANCES:
        logging.info(f"🚀 Cobalt API orqali yuklanmoqda: {target_url}")
        file_path = await _download_via_cobalt(target_url, out_file)
        if file_path:
            return file_path, track_title or "Audio Track", None

    logging.error(f"❌ Barcha usullar muvaffaqiyatsiz tugadi: {target_url}")
    return None, "Audio Track", None


async def _download_via_cobalt(target_url: str, out_file: str) -> str | None:
    payload = {"url": target_url, "downloadMode": "audio", "audioFormat": "mp3"}
    headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT}
    if COBALT_API_KEY:
        headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"

    for instance in COBALT_INSTANCES:
        try:
            async with get_session() as session:
                async with session.post(instance, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        download_url = data.get("url")
                        if download_url:
                            async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=45)) as file_resp:
                                if file_resp.status == 200:
                                    with open(out_file, 'wb') as f:
                                        async for chunk in file_resp.content.iter_chunked(16384):
                                            f.write(chunk)
                                    if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                                        logging.info("✅ Cobalt API orqali muvaffaqiyatli yuklandi.")
                                        return out_file
                    else:
                        logging.warning(f"Cobalt ({instance}) status: {resp.status}")
        except Exception as e:
            logging.warning(f"Cobalt ({instance}) xatosi: {e}")
            continue
    return None


async def _download_via_piped(video_id: str, out_file: str) -> str | None:
    for instance in PIPED_INSTANCES:
        try:
            api_url = f"{instance}/streams/{video_id}"
            async with get_session() as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status != 200:
                        logging.warning(f"Piped ({instance}) status: {resp.status}")
                        continue
                    data = await resp.json()
                    audio_streams = data.get("audioStreams", [])
                    if not audio_streams:
                        continue
                    best_audio = max(audio_streams, key=lambda x: int(x.get("bitrate", 0)))
                    download_url = best_audio.get("url")
                    if not download_url:
                        continue
                    async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=30)) as file_resp:
                        if file_resp.status == 200:
                            with open(out_file, 'wb') as f:
                                async for chunk in file_resp.content.iter_chunked(16384):
                                    f.write(chunk)
                            if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                                logging.info(f"✅ Piped API orqali muvaffaqiyatli yuklandi ({instance}).")
                                return out_file
        except Exception as e:
            logging.warning(f"Piped ({instance}) xatosi: {e}")
            continue
    return None


async def _download_via_invidious(video_id: str, out_file: str) -> str | None:
    for instance in INVIDIOUS_INSTANCES:
        try:
            api_url = f"{instance}/api/v1/videos/{video_id}"
            async with get_session() as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status != 200:
                        logging.warning(f"Invidious ({instance}) status: {resp.status}")
                        continue
                    data = await resp.json()
                    adaptive_formats = data.get("adaptiveFormats", [])
                    audio_streams = [f for f in adaptive_formats if f.get("type", "").startswith("audio/")]
                    if not audio_streams:
                        continue
                    best_audio = max(audio_streams, key=lambda x: int(x.get("bitrate", 0)))
                    download_url = best_audio.get("url")
                    if not download_url:
                        continue
                    async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=30)) as file_resp:
                        if file_resp.status == 200:
                            with open(out_file, 'wb') as f:
                                async for chunk in file_resp.content.iter_chunked(16384):
                                    f.write(chunk)
                            if os.path.exists(out_file) and os.path.getsize(out_file) > 10240:
                                logging.info(f"✅ Invidious API orqali muvaffaqiyatli yuklandi ({instance}).")
                                return out_file
        except Exception as e:
            logging.warning(f"Invidious ({instance}) xatosi: {e}")
            continue
    return None


# PO Token provider (bgutil-ytdlp-pot-provider) o'rnatilgan bo'lsa, yt-dlp
# standart client'lar (masalan 'web', 'tvhtml5') orqali ham cookie+PO token
# bilan ishlashi mumkin — bu hozirgi (2026) YouTube bot-tekshiruvidan o'tishning
# asosiy yo'li, chunki PO token'siz deyarli har qanday client vaqti-vaqti
# bilan "Sign in to confirm you're not a bot" bilan bloklanadi.
# Shu sabab birinchi urinishda player_client'ni MAJBURLAMAYMIZ — yt-dlp o'zi
# PO token plugin orqali eng mos client'ni tanlaydi. Faqat shu urinish
# muvaffaqiyatsiz bo'lsa, aniq client'larni birma-bir sinaymiz.
client_configs = [
    (['mweb'], True),         # yt-dlp'ning rasmiy tavsiyasi: mweb + PO Token
    (None, True),             # standart (yt-dlp o'zi client tanlaydi)
    (['tv_embedded'], False),
    (['ios'], False),
    (['android'], False),
    (['web_creator'], True),
]

# YouTube ketma-ket keladigan so'rovlarni "hujum" deb hisoblab, IP'ni tezroq
# bloklaydi. Urinishlar orasiga qisqa tanaffus qo'shish IP obro'sini saqlashga
# yordam beradi (yt-dlp hujjatlaridagi tavsiya).
_RETRY_DELAY_SECONDS = 2


def _download_ytdlp_client_sync(target_url: str, file_prefix: str, track_title: str = None) -> tuple[str | None, str]:
    last_error = None

    for attempt, (clients, use_cookies) in enumerate(client_configs):
        try:
            opts = {
                'format': 'ba/b',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'overwrites': True,
                'quiet': True,
                'no_warnings': True,
                'retries': 2,
                'socket_timeout': 20,
                'http_headers': {
                    'User-Agent': USER_AGENT,
                }
            }

            extractor_args = _build_youtube_extractor_args(clients)
            if extractor_args:
                opts['extractor_args'] = extractor_args

            if use_cookies and COOKIES_FILE and os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
                opts['cookiefile'] = COOKIES_FILE

            if FFMPEG_PATH:
                opts['ffmpeg_location'] = FFMPEG_PATH
                opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                title = info.get('title', track_title or 'Audio Track') if info else 'Audio Track'

                for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")):
                    if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                        return f, title
        except Exception as e:
            last_error = e
            logging.warning(f"yt-dlp ({clients or 'default'}) urinishi xatosi: {e}")
            if attempt < len(client_configs) - 1:
                time.sleep(_RETRY_DELAY_SECONDS)
            continue

    if last_error:
        logging.error(f"yt-dlp barcha client'lar bilan muvaffaqiyatsiz: {last_error}")
    return None, "Audio Track"


def _download_video_ytdlp_sync(target_url: str, file_prefix: str) -> tuple[str | None, str]:
    """download_media avval faqat Cobalt'ga tayangan edi — Cobalt instance
    ishlamay qolsa (masalan kalitsiz 400 xatosi), video umuman yuklanmasdi.
    Endi audio funksiyasidagi kabi yt-dlp orqali ham urinib ko'riladi."""
    for clients, use_cookies in client_configs:
        try:
            opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'overwrites': True,
                'quiet': True,
                'no_warnings': True,
                'retries': 2,
                'socket_timeout': 20,
                'http_headers': {'User-Agent': USER_AGENT},
            }
            extractor_args = _build_youtube_extractor_args(clients)
            if extractor_args:
                opts['extractor_args'] = extractor_args
            if use_cookies and COOKIES_FILE and os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
                opts['cookiefile'] = COOKIES_FILE
            if FFMPEG_PATH:
                opts['ffmpeg_location'] = FFMPEG_PATH

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                title = info.get('title', 'Video') if info else 'Video'
                for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*")):
                    if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 10240:
                        return f, title
        except Exception as e:
            logging.warning(f"yt-dlp video ({clients or 'default'}) urinishi xatosi: {e}")
            time.sleep(_RETRY_DELAY_SECONDS)
            continue
    return None, "Video"


async def download_media(url: str) -> dict:
    url = url.strip()
    file_prefix = "video_" + str(abs(hash(url)))[-8:]
    v_file = os.path.join(DOWNLOAD_DIR, f"{file_prefix}.mp4")

    try:
        await asyncio.wait_for(_refresh_instances(), timeout=10)
    except Exception:
        pass

    # 1-Bosqich: yt-dlp (PO token + cookie bilan, YouTube va boshqa ko'plab
    # saytlar uchun ishlaydi)
    logging.info(f"🚀 yt-dlp orqali video yuklanmoqda: {url}")
    file_path, title = await asyncio.to_thread(_download_video_ytdlp_sync, url, file_prefix)
    if file_path:
        return {"file_path": file_path, "title": title, "id": file_prefix}

    # 2-Bosqich: Cobalt API (yt-dlp qo'llamaydigan ba'zi platformalar uchun ham foydali)
    for instance in COBALT_INSTANCES:
        try:
            payload = {"url": url, "downloadMode": "auto"}
            headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT}
            if COBALT_API_KEY:
                headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"

            async with get_session() as session:
                async with session.post(instance, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        v_url = data.get("url")
                        if v_url:
                            async with session.get(v_url, timeout=aiohttp.ClientTimeout(total=60)) as file_resp:
                                if file_resp.status == 200:
                                    with open(v_file, 'wb') as f:
                                        async for chunk in file_resp.content.iter_chunked(8192):
                                            f.write(chunk)
                                    if os.path.exists(v_file) and os.path.getsize(v_file) > 10240:
                                        return {"file_path": v_file, "title": "Video", "id": file_prefix}
                    else:
                        logging.warning(f"Cobalt ({instance}) status: {resp.status}")
        except Exception as e:
            logging.warning(f"Cobalt media ({instance}) xatosi: {e}")
            continue

    return {"file_path": None, "title": "Video", "id": None}
