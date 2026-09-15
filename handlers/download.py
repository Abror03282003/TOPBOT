import os
import logging

from aiogram import Router, F
from aiogram.types import Message, FSInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.url_validator import extract_url
from services.downloader import download_media, search_media, cleanup_file, DownloadError
from config import MAX_FILE_SIZE

router = Router()
logger = logging.getLogger(__name__)

PAGE_SIZE = 10

# So'nggi yuborilgan video linkni saqlab turamiz (audio tugmasi shundan foydalanadi)
_last_url: dict[int, str] = {}
# So'nggi qidiruv natijalarini saqlab turamiz
_last_search: dict[int, list] = {}


def _build_video_keyboard(bot_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="💾 Saqlash", callback_data="save_info")
    builder.button(text="🎵 Qo'shiqni yuklab olish", callback_data="dl_audio")
    builder.button(
        text="➕ Guruhga qo'shish",
        url=f"https://t.me/{bot_username}?startgroup=true",
    )
    builder.adjust(1)
    return builder.as_markup()


def _render_search_page(query: str, results: list, page: int):
    total = len(results)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_items = results[start:end]

    lines = [f"🔎 <b>{query}</b>\n"]
    for offset, item in enumerate(page_items):
        num = start + offset + 1
        dur = f" {item['duration']}" if item["duration"] else ""
        lines.append(f"{num}. {item['title']}{dur}")
    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    for offset in range(len(page_items)):
        abs_idx = start + offset
        builder.button(text=str(offset + 1 + start), callback_data=f"srch:{abs_idx}")
    row_sizes = [5] * (len(page_items) // 5)
    if len(page_items) % 5:
        row_sizes.append(len(page_items) % 5)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(("⬅️", f"srch_page:{page - 1}"))
    nav_buttons.append(("❌", "srch_cancel"))
    if end < total:
        nav_buttons.append(("➡️", f"srch_page:{page + 1}"))

    for label, data in nav_buttons:
        builder.button(text=label, callback_data=data)
    row_sizes.append(len(nav_buttons))

    builder.adjust(*row_sizes)
    return text, builder.as_markup()


@router.message(F.text)
async def handle_message(message: Message):
    url = extract_url(message.text)
    bot_info = await message.bot.get_me()

    if url:
        _last_url[message.from_user.id] = url
        status = await message.answer("⏳ Yuklanmoqda, biroz kuting...")

        filepath = None
        try:
            filepath = await download_media(url, audio_only=False)

            if os.path.getsize(filepath) > MAX_FILE_SIZE:
                await status.edit_text(
                    "⚠️ Fayl hajmi 50MB dan katta, Telegram orqali yuborib bo'lmaydi."
                )
                return

            file = FSInputFile(filepath)
            caption = f"📥 @{bot_info.username} orqali yuklab olindi"
            await message.answer_video(
                file,
                caption=caption,
                reply_markup=_build_video_keyboard(bot_info.username),
            )
            await status.delete()

        except DownloadError as e:
            logger.warning(f"Yuklashda xato: {e}")
            await status.edit_text(
                "❌ Video yuklab bo'lmadi. Link noto'g'ri, private akkaunt "
                "yoki video o'chirilgan bo'lishi mumkin."
            )
        except Exception:
            logger.exception("Kutilmagan xato")
            await status.edit_text("❌ Nimadir xato ketdi. Keyinroq urinib ko'ring.")
        finally:
            cleanup_file(filepath)

    else:
        query = message.text.strip()
        if len(query) < 2:
            await message.answer(
                "Menga video linki yoki qidirmoqchi bo'lgan qo'shiq nomini yuboring."
            )
            return

        status = await message.answer(f"🔍 \"{query}\" qidirilmoqda...")
        try:
            results = await search_media(query, limit=30)
        except Exception:
            logger.exception("Qidirishda xato")
            await status.edit_text("❌ Qidirishda xato yuz berdi. Qayta urinib ko'ring.")
            return

        if not results:
            await status.edit_text(
                "❌ Hech narsa topilmadi. Boshqacha nom bilan urinib ko'ring."
            )
            return

        _last_search[message.from_user.id] = results
        text, keyboard = _render_search_page(query, results, page=0)
        await status.delete()
        await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("srch_page:"))
async def handle_search_page(callback: CallbackQuery):
    user_id = callback.from_user.id
    results = _last_search.get(user_id)
    if not results:
        await callback.answer("Qidiruv natijasi topilmadi, qaytadan qidiring.", show_alert=True)
        return

    page = int(callback.data.split(":")[1])
    query = callback.message.text.splitlines()[0].replace("🔎 ", "").strip()
    text, keyboard = _render_search_page(query, results, page)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "srch_cancel")
async def handle_search_cancel(callback: CallbackQuery):
    _last_search.pop(callback.from_user.id, None)
    await callback.message.delete()
    await callback.answer("Bekor qilindi.")


@router.callback_query(F.data.startswith("srch:"))
async def handle_search_choice(callback: CallbackQuery):
    user_id = callback.from_user.id
    results = _last_search.get(user_id)
    if not results:
        await callback.answer("Qidiruv natijasi topilmadi, qaytadan qidiring.", show_alert=True)
        return

    idx = int(callback.data.split(":")[1])
    if idx >= len(results):
        await callback.answer("Noto'g'ri tanlov.", show_alert=True)
        return

    chosen = results[idx]
    await callback.answer("⏳ Yuklanmoqda...")
    await callback.message.edit_text(f"⏳ Yuklanmoqda: {chosen['title']}")

    filepath = None
    try:
        video_url = f"https://www.youtube.com/watch?v={chosen['id']}"
        filepath = await download_media(video_url, audio_only=True)

        if os.path.getsize(filepath) > MAX_FILE_SIZE:
            await callback.message.edit_text("⚠️ Fayl hajmi 50MB dan katta.")
            return

        file = FSInputFile(filepath)
        bot_info = await callback.bot.get_me()
        caption = f"📥 @{bot_info.username} orqali yuklab olindi"
        await callback.message.answer_audio(file, caption=caption)
        await callback.message.delete()

    except DownloadError as e:
        logger.warning(f"Audio yuklashda xato: {e}")
        await callback.message.edit_text(
            "❌ Yuklab bo'lmadi. Boshqa natijani sinab ko'ring."
        )
    except Exception:
        logger.exception("Kutilmagan xato")
        await callback.message.edit_text("❌ Nimadir xato ketdi.")
    finally:
        cleanup_file(filepath)


@router.callback_query(F.data == "save_info")
async def handle_save_info(callback: CallbackQuery):
    await callback.answer(
        "Video yuqorida ✅ Uni uzoq bosib 'Forward' orqali istalgan "
        "chatga yoki 'Saqlangan xabarlar'ga yuborishingiz mumkin.",
        show_alert=True,
    )


@router.callback_query(F.data.in_({"dl_video", "dl_audio"}))
async def handle_audio_download(callback: CallbackQuery):
    user_id = callback.from_user.id
    url = _last_url.get(user_id)

    if not url:
        await callback.answer("Link topilmadi, qaytadan yuboring.", show_alert=True)
        return

    await callback.answer("⏳ Audio tayyorlanmoqda...")

    filepath = None
    try:
        filepath = await download_media(url, audio_only=True)

        if os.path.getsize(filepath) > MAX_FILE_SIZE:
            await callback.message.answer("⚠️ Fayl hajmi 50MB dan katta.")
            return

        file = FSInputFile(filepath)
        await callback.message.answer_audio(file)

    except DownloadError as e:
        logger.warning(f"Audio yuklashda xato: {e}")
        await callback.message.answer(
            "❌ Audio yuklab bo'lmadi. Link noto'g'ri yoki video o'chirilgan bo'lishi mumkin."
        )
    except Exception:
        logger.exception("Kutilmagan xato")
        await callback.message.answer("❌ Nimadir xato ketdi.")
    finally:
        cleanup_file(filepath)
