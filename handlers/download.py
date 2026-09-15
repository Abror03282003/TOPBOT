import os
import uuid
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from services.downloader import search_tracks, download_media, download_audio_by_id

router = Router()

SEARCH_CACHE = {}


def build_search_keyboard(items: list[dict], search_id: str) -> InlineKeyboardMarkup:
    """1-5, 6-10 va pastki boshqaruv tugmalarini yaratish."""
    keyboard = []
    
    # 1-qator: 1 2 3 4 5
    row1 = []
    for i in range(1, min(6, len(items) + 1)):
        row1.append(InlineKeyboardButton(text=str(i), callback_data=f"dl_{search_id}_{i-1}"))
    keyboard.append(row1)
    
    # 2-qator: 6 7 8 9 10
    if len(items) > 5:
        row2 = []
        for i in range(6, len(items) + 1):
            row2.append(InlineKeyboardButton(text=str(i), callback_data=f"dl_{search_id}_{i-1}"))
        keyboard.append(row2)
        
    # 3-qator: ⬅️ ❌ ➡️
    control_row = [
        InlineKeyboardButton(text="⬅️", callback_data="nop"),
        InlineKeyboardButton(text="❌", callback_data=f"close_{search_id}"),
        InlineKeyboardButton(text="➡️", callback_data="nop")
    ]
    keyboard.append(control_row)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(F.text.startswith("http"))
async def handle_link(message: Message):
    msg = await message.answer("⏳ Video yuklanmoqda...")
    try:
        data = await download_media(message.text)
        file_path = data.get("file_path")
        
        if file_path and os.path.exists(file_path):
            video_file = FSInputFile(file_path)
            await message.answer_video(
                video=video_file, 
                caption=data.get("title", "")[:1024]
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
        results = await search_tracks(message.text, limit=10)
        if not results:
            await msg.edit_text("❌ Hech narsa topilmadi.")
            return
        
        search_id = str(uuid.uuid4())[:8]
        SEARCH_CACHE[search_id] = results
        
        text = f"🔍 <b>{message.text}</b>\n\n"
        for i, item in enumerate(results, 1):
            text += f"<b>{i}.</b> {item['title']} <b>{item['duration']}</b>\n"
            
        markup = build_search_keyboard(results, search_id)
        await msg.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        await msg.edit_text(f"❌ Qidiruvda xatolik yuz berdi.")


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


@router.callback_query(F.data == "nop")
async def handle_nop_callback(call: CallbackQuery):
    await call.answer()
