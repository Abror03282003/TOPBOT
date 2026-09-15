import os
import uuid
import subprocess
import imageio_ffmpeg
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from shazamio import Shazam
from services.downloader import search_tracks, download_media, download_audio_by_id

router = Router()

BOT_USERNAME = "top_botuz_bot"  # Botingiz username'i
SEARCH_CACHE = {}


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
    """Sahifa bo'yicha matn va har bir sahifada 1-10 tugmalarni shakllantirish."""
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
    
    # 1-qator: 1 2 3 4 5
    row1 = []
    for btn_num, real_idx in enumerate(range(start_idx, min(start_idx + 5, end_idx)), 1):
        row1.append(InlineKeyboardButton(text=str(btn_num), callback_data=f"dl_{search_id}_{real_idx}"))
    if row1:
        keyboard.append(row1)
        
    # 2-qator: 6 7 8 9 10
    if end_idx > start_idx + 5:
        row2 = []
        for btn_num, real_idx in enumerate(range(start_idx + 5, end_idx), 6):
            row2.append(InlineKeyboardButton(text=str(btn_num), callback_data=f"dl_{search_id}_{real_idx}"))
        keyboard.append(row2)
        
    # 3-qator: ⬅️ ❌ ➡️
    prev_page = page - 1 if page > 0 else total_pages - 1
    next_page = page + 1 if page < total_pages - 1 else 0
    
    control_row = [
        InlineKeyboardButton(text="⬅️", callback_data=f"page_{search_id}_{prev_page}"),
        InlineKeyboardButton(text="❌", callback_data=f"close_{search_id}"),
        InlineKeyboardButton(text="➡️", callback_data=f"page_{search_id}_{next_page}")
    ]
    keyboard.append(control_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(F.text.startswith("http"))
async def handle_link(message: Message):
    msg = await message.answer("⏳ Video yuklanmoqda...")
    try:
        data = await download_media(message.text)
        file_path = data.get("file_path")
        
        if file_path and os.path.exists(file_path):
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
            await msg.edit_text("❌ Fayl topilmadi.")
    except Exception as e:
        await msg.edit_text(f"❌ Yuklashda xatolik yuz berdi: {e}")


@router.message(F.text)
async def handle_search(message: Message):
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
        await msg.edit_text(f"❌ Qidiruvda xatolik yuz berdi.")


@router.callback_query(F.data == "save_to_saved_messages")
async def handle_save_to_saved(call: CallbackQuery):
    """Videoni 'Saqlangan xabarlar'ga yuborish."""
    try:
        await call.bot.copy_message(
            chat_id=call.from_user.id,
            from_chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        await call.answer("✅ 'Saqlangan xabarlar'ga yuborildi!", show_alert=True)
    except Exception:
        await call.answer("❌ Saqlashda xatolik yuz berdi.", show_alert=True)


@router.callback_query(F.data == "identify_and_search_song")
async def handle_identify_song(call: CallbackQuery):
    """Videodagi qo'shiqni ajratib olish, Shazam orqali tanish va qidiruv natijalarini chiqarish."""
    await call.answer("🔍 Qo'shiq aniqlanmoqda...")
    status_msg = await call.message.answer("🎧 Videodagi qo'shiq eshitib ko'rilmoqda...")
    
    input_file = None
    audio_file = None
    try:
        if call.message.video:
            os.makedirs("downloads", exist_ok=True)
            file_id = call.message.video.file_id
            file_info = await call.bot.get_file(file_id)
            
            file_hash = uuid.uuid4().hex[:6]
            input_file = f"downloads/temp_{file_hash}.mp4"
            audio_file = f"downloads/audio_{file_hash}.wav"
            
            # Videoni serverga yuklab olish
            await call.bot.download_file(file_info.file_path, input_file)
            
            # imageio-ffmpeg orqali FFmpeg yo'lagini olish
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            
            # FFmpeg orqali videoning birinchi 20 sekundini WAV (PCM s16le) formatida kesib olish
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
                err_details = process.stderr[-200:] if process.stderr else "Noma'lum FFmpeg xatoligi"
                await status_msg.edit_text(f"❌ Audioni ajratishda xatolik:\n<code>{err_details}</code>", parse_mode="HTML")
                return

            # Shazam orqali tanish
            shazam = Shazam()
            out = await shazam.recognize(audio_file)
            
            track = out.get('track')
            if track:
                title = track.get('title', '')
                subtitle = track.get('subtitle', '')
                full_song_name = f"{subtitle} {title}".strip()
                
                await status_msg.edit_text(f"🎵 Topilgan qo'shiq: <b>{full_song_name}</b>\n🔍 To'liq versiyalari qidirilmoqda...", parse_mode="HTML")
                
                # YouTube'dan qidirish
                results = await search_tracks(full_song_name, limit=30)
                if results:
                    search_id = str(uuid.uuid4())[:8]
                    SEARCH_CACHE[search_id] = results
                    text, markup = render_page(results, search_id, page=0)
                    await status_msg.edit_text(text, reply_markup=markup, parse_mode="HTML")
                else:
                    await status_msg.edit_text(f"❌ Qo'shiq aniqlandi: <b>{full_song_name}</b>, lekin mp3 versiyasi topilmadi.", parse_mode="HTML")
            else:
                await status_msg.edit_text("❌ Afsuski, videodagi qo'shiq aniqlanmadi (Shazam topa olmadi).")
        else:
            await status_msg.edit_text("❌ Video topilmadi.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ishlov berishda xatolik: {e}")
    finally:
        if input_file and os.path.exists(input_file):
            os.remove(input_file)
        if audio_file and os.path.exists(audio_file):
            os.remove(audio_file)


@router.callback_query(F.data.startswith("page_"))
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
    search_id = parts[1]
    index = int(parts[2])
    
    results = SEARCH_CACHE.get(search_id)
    if not results or index >= len(results):
        await call.answer("❌ Natija eskirgan. Iltimos qayta qidiring.", show_alert=True)
        return

    item = results[index]
    await call.answer(f"⏳ '{item['title'][:20]}' yuklanmoqda...")
    status_msg = await call.message.answer(f"⏳ <b>{item['title']}</b> yuklanmoqda...", parse_mode="HTML")
    
    try:
        file_path, title = await download_audio_by_id(item['id'])
        if file_path and os.path.exists(file_path):
            audio_file = FSInputFile(file_path)
            await call.message.answer_audio(
                audio=audio_file,
                title=title
            )
            os.remove(file_path)
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Audio fayl topilmadi.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Audio yuklashda xatolik: {e}")


@router.callback_query(F.data.startswith("close_"))
async def handle_close_callback(call: CallbackQuery):
    search_id = call.data.replace("close_", "")
    if search_id in SEARCH_CACHE:
        del SEARCH_CACHE[search_id]
    await call.message.delete()
    await call.answer("O'chirildi")
