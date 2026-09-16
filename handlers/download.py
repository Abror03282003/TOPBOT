import os
import uuid
import subprocess
import urllib.parse
import logging
import imageio_ffmpeg
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from shazamio import Shazam
from services.downloader import search_tracks, download_media, download_audio_by_id
from database import add_user

router = Router()

BOT_USERNAME = "top_botuz_bot"
SEARCH_CACHE = {}


def build_song_keyboard(song_name: str) -> InlineKeyboardMarkup:
    """Qo'shiq yuklangandan keyin chiqariladigan tugmalar."""
    safe_name = song_name[:25]
    encoded_name = urllib.parse.quote(safe_name)
    
    keyboard = [
        [
            InlineKeyboardButton(text="📜 Musiqa matni (Lyrics)", callback_data=f"lyr_{encoded_name}")
        ],
        [
            InlineKeyboardButton(text="💾 Saqlash", callback_data="save_to_saved_messages")
        ],
        [
            InlineKeyboardButton(
                text="Guruhga qo'shish ⤴️", 
                url=f"https://t.me/{BOT_USERNAME}?startgroup=true"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_video_keyboard() -> InlineKeyboardMarkup:
    """Video ostidagi tugmalar paneli."""
    keyboard = [
        [
            InlineKeyboardButton(text="💾 Saqlash", callback_data="save_to_saved_messages")
        ],
        [
            InlineKeyboardButton(text="📩 Qo'shiqni yuklab olish", callback_data="identify_and_search_song")
        ],
        [
            InlineKeyboardButton(
                text="Guruhga qo'shish ⤴️", 
                url=f"https://t.me/{BOT_USERNAME}?startgroup=true"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def render_page(results: list[dict], search_id: str, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    """Sahifa bo'yicha matn va har doim 1-10 tartibli tugmalarni shakllantirish."""
    per_page = 10
    total_items = len(results)
    total_pages = (total_items + per_page - 1) // per_page
    
    page = max(0, min(page, total_pages - 1))
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, total_items)
    
    current_items = results[start_idx:end_idx]
    
    text = f"🔍 Topilgan qo'shiqlar (Sahifa {page + 1}/{total_pages}):\n\n"
    for i, item in enumerate(current_items, start=start_idx + 1):
        text += f"<b>{i}.</b> {item['title']} <b>{item['duration']}</b>\n"
        
    keyboard = []
    
    # 1-qator (1, 2, 3, 4, 5)
    row1 = []
    for btn_num, real_idx in enumerate(range(start_idx, min(start_idx + 5, end_idx)), 1):
        row1.append(InlineKeyboardButton(text=str(btn_num), callback_data=f"dl_{search_id}_{real_idx}"))
    if row1:
        keyboard.append(row1)
        
    # 2-qator (6, 7, 8, 9, 10)
    if end_idx > start_idx + 5:
        row2 = []
        for btn_num, real_idx in enumerate(range(start_idx + 5, end_idx), 6):
            row2.append(InlineKeyboardButton(text=str(btn_num), callback_data=f"dl_{search_id}_{real_idx}"))
        keyboard.append(row2)
        
    # Navigatsiya (⬅️ ❌ ➡️)
    prev_page = page - 1 if page > 0 else total_pages - 1
    next_page = page + 1 if page < total_pages - 1 else 0
    
    control_row = [
        InlineKeyboardButton(text="⬅️", callback_data=f"p_{search_id}_{prev_page}"),
        InlineKeyboardButton(text="❌", callback_data=f"cl_{search_id}"),
        InlineKeyboardButton(text="➡️", callback_data=f"p_{search_id}_{next_page}")
    ]
    keyboard.append(control_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


async def process_media_for_shazam(message: Message, file_id: str) -> tuple[str | None, str | None]:
    """Har qanday media fayldan 20 sekundlik WAV kesib olish va Shazam orqali tanish."""
    os.makedirs("downloads", exist_ok=True)
    file_info = await message.bot.get_file(file_id)
    
    file_hash = uuid.uuid4().hex[:6]
    input_file = f"downloads/temp_{file_hash}.file"
    audio_file = f"downloads/audio_{file_hash}.wav"
    
    try:
        await message.bot.download_file(file_info.file_path, input_file)
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        cmd = [
            ffmpeg_exe, "-y",
            "-i", input_file,
            "-t", "20",
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            audio_file
        ]
        
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if process.returncode != 0 or not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
            return None, "Audio ishlovida xatolik"

        shazam = Shazam()
        out = await shazam.recognize(audio_file)
        track = out.get('track')
        
        if track:
            title = track.get('title', '')
            subtitle = track.get('subtitle', '')
            return f"{subtitle} {title}".strip(), None
        return None, "Qo'shiq aniqlanmadi (Shazam topa olmadi)"
    finally:
        if os.path.exists(input_file):
            try:
                os.remove(input_file)
            except Exception:
                pass
        if os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except Exception:
                pass


@router.message(F.text.startswith("http"))
async def handle_link(message: Message):
    add_user(message.from_user.id, message.from_user.full_name, message.from_user.username or "")
    msg = await message.answer("⏳ Video yuklanmoqda...")
    try:
        data = await download_media(message.text)
        file_path = data.get("file_path")
        
        if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            video_file = FSInputFile(file_path)
            caption_text = f"📩 @{BOT_USERNAME} orqali yuklab olindi"
            
            await message.answer_video(
                video=video_file, 
                caption=caption_text,
                reply_markup=build_video_keyboard()
            )
            os.remove(file_path)
            await msg.delete()
        else:
            await msg.edit_text("❌ Fayl topilmadi yoki yuklab bo'lmadi.")
    except Exception as e:
        await msg.edit_text(f"❌ Yuklashda xatolik yuz berdi: {e}")


@router.message(F.text & ~F.text.startswith("/"))
async def handle_search(message: Message):
    add_user(message.from_user.id, message.from_user.full_name, message.from_user.username or "")
    msg = await message.answer("🔍 Qidirilmoqda...")
    try:
        results = await search_tracks(message.text, limit=30)
        if not results:
            await msg.edit_text("❌ Hech narsa topilmadi.")
            return
        
        search_id = str(uuid.uuid4())[:8]
        SEARCH_CACHE[search_id] = results
        
        text, markup = render_page(results, search_id, page=0)
        await msg.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Search error: {e}")
        await msg.edit_text("❌ Qidiruvda xatolik yuz berdi.")


@router.message(F.voice | F.video_note | F.audio)
async def handle_all_media_types(message: Message):
    add_user(message.from_user.id, message.from_user.full_name, message.from_user.username or "")
    status_msg = await message.answer("🎧 Tashlangan media eshitib ko'rilmoqda...")
    
    file_id = None
    if message.voice:
        file_id = message.voice.file_id
    elif message.video_note:
        file_id = message.video_note.file_id
    elif message.audio:
        file_id = message.audio.file_id

    if not file_id:
        await status_msg.edit_text("❌ Media topshirishda xatolik.")
        return

    song_name, err = await process_media_for_shazam(message, file_id)
    if err or not song_name:
        await status_msg.edit_text("❌ Afsuski, ushbu audiodan qo'shiq aniqlanmadi.")
        return

    await status_msg.edit_text(f"🎵 Topilgan qo'shiq: <b>{song_name}</b>\n🔍 To'liq mp3 versiyalari qidirilmoqda...", parse_mode="HTML")
    
    results = await search_tracks(song_name, limit=30)
    if results:
        search_id = str(uuid.uuid4())[:8]
        SEARCH_CACHE[search_id] = results
        text, markup = render_page(results, search_id, page=0)
        await status_msg.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await status_msg.edit_text(f"❌ Qo'shiq aniqlandi: <b>{song_name}</b>, lekin mp3 versiyasi topilmadi.", parse_mode="HTML")


@router.callback_query(F.data == "identify_and_search_song")
async def handle_identify_song(call: CallbackQuery):
    await call.answer("🔍 Qo'shiq aniqlanmoqda...")
    status_msg = await call.message.answer("🎧 Videodagi qo'shiq eshitib ko'rilmoqda...")
    
    if call.message.video:
        file_id = call.message.video.file_id
        song_name, err = await process_media_for_shazam(call.message, file_id)
        
        if err or not song_name:
            await status_msg.edit_text("❌ Afsuski, videodagi qo'shiq aniqlanmadi.")
            return

        await status_msg.edit_text(f"🎵 Topilgan qo'shiq: <b>{song_name}</b>\n🔍 To'liq versiyalari qidirilmoqda...", parse_mode="HTML")
        
        results = await search_tracks(song_name, limit=30)
        if results:
            search_id = str(uuid.uuid4())[:8]
            SEARCH_CACHE[search_id] = results
            text, markup = render_page(results, search_id, page=0)
            await status_msg.edit_text(text, reply_markup=markup, parse_mode="HTML")
        else:
            await status_msg.edit_text(f"❌ Qo'shiq aniqlandi: <b>{song_name}</b>, lekin mp3 versiyasi topilmadi.", parse_mode="HTML")
    else:
        await status_msg.edit_text("❌ Video topilmadi.")


@router.callback_query(F.data.startswith("lyr_"))
async def handle_lyrics_callback(call: CallbackQuery):
    song_name = urllib.parse.unquote(call.data.replace("lyr_", ""))
    await call.answer("📜 Matn tayyorlanmoqda...")
    
    query = urllib.parse.quote(f"{song_name} lyrics matni")
    search_url = f"https://www.google.com/search?q={query}"
    
    text = (
        f"📜 <b>{song_name}</b> - Musiqa matni\n\n"
        f"<i>To'liq matn va tarjimasini litsenziyalangan manbalardan o'qish uchun quyidagi havola orqali o'ting:</i>\n\n"
        f"🔗 <a href='{search_url}'>To'liq matnni Google'da ko'rish</a>"
    )
    await call.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data == "save_to_saved_messages")
async def handle_save_to_saved(call: CallbackQuery):
    try:
        await call.bot.copy_message(
            chat_id=call.from_user.id,
            from_chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        await call.answer("✅ 'Saqlangan xabarlar'ga yuborildi!", show_alert=True)
    except Exception:
        await call.answer("❌ Saqlashda xatolik yuz berdi.", show_alert=True)


@router.callback_query(F.data.startswith("p_"))
async def handle_page_callback(call: CallbackQuery):
    parts = call.data.split("_")
    search_id = parts[1]
    target_page = int(parts[2])
    
    results = SEARCH_CACHE.get(search_id)
    if not results:
        await call.answer("❌ Qidiruv natijasi eskirgan. Qayta qidiring.", show_alert=True)
        return
        
    text, markup = render_page(results, search_id, page=target_page)
    try:
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("dl_"))
async def handle_download_callback(call: CallbackQuery):
    parts = call.data.split("_")
    if len(parts) < 3:
        await call.answer("❌ Noto'g'ri so'rov.", show_alert=True)
        return

    search_id = parts[1]
    index = int(parts[2])
    
    results = SEARCH_CACHE.get(search_id)
    if not results or index >= len(results):
        await call.answer("❌ Natija eskirgan. Iltimos, qayta qidiring.", show_alert=True)
        return

    item = results[index]
    await call.answer(f"⏳ '{item['title'][:20]}' yuklanmoqda...")
    status_msg = await call.message.answer(f"⏳ <b>{item['title']}</b> yuklanmoqda...", parse_mode="HTML")
    
    try:
        track_id = item.get('id')
        file_path, title = await download_audio_by_id(track_id)
        
        if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            audio_file = FSInputFile(file_path)
            
            await call.message.answer_audio(
                audio=audio_file,
                title=title or item.get('title'),
                reply_markup=build_song_keyboard(title or item.get('title'))
            )
            
            try:
                os.remove(file_path)
            except Exception as e:
                logging.error(f"Faylni o'chirishda xatolik: {e}")
                
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Audio fayl topilmadi yoki yuklash imkonsiz bo'ldi.")
    except Exception as e:
        logging.error(f"Download callback xatosi: {e}")
        await status_msg.edit_text(f"❌ Audio yuklashda xatolik: {e}")


@router.callback_query(F.data.startswith("cl_"))
async def handle_close_callback(call: CallbackQuery):
    search_id = call.data.replace("cl_", "")
    if search_id in SEARCH_CACHE:
        del SEARCH_CACHE[search_id]
    await call.message.delete()
    await call.answer("O'chirildi")
