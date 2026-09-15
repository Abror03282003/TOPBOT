import os
import logging

from aiogram import Router, F
from aiogram.types import Message, FSInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.url_validator import extract_url, detect_platform
from services.downloader import download_media, cleanup_file, DownloadError
from config import MAX_FILE_SIZE

router = Router()
logger = logging.getLogger(__name__)

_last_url: dict[int, str] = {}


@router.message(F.text)
async def handle_message(message: Message):
    url = extract_url(message.text)

    if not url:
        await message.answer(
            "Iltimos, menga to'g'ri video linki yuboring "
            "(Instagram, TikTok, YouTube va h.k.)."
        )
        return

    platform = detect_platform(url)
    _last_url[message.from_user.id] = url

    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Video", callback_data="dl_video")
    builder.button(text="🎵 Faqat audio (mp3)", callback_data="dl_audio")

    await message.answer(
        f"Aniqlandi: <b>{platform}</b>\nNimani yuklab beray?",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.in_({"dl_video", "dl_audio"}))
async def handle_download_choice(callback: CallbackQuery):
    user_id = callback.from_user.id
    url = _last_url.get(user_id)

    if not url:
        await callback.answer("Link topilmadi, qaytadan yuboring.", show_alert=True)
        return

    audio_only = callback.data == "dl_audio"

    await callback.message.edit_text("⏳ Yuklanmoqda, biroz kuting...")
    await callback.answer()

    filepath = None
    try:
        filepath = await download_media(url, audio_only=audio_only)

        if os.path.getsize(filepath) > MAX_FILE_SIZE:
            await callback.message.edit_text(
                "⚠️ Fayl hajmi 50MB dan katta, Telegram orqali yuborib bo'lmaydi."
            )
            return

        file = FSInputFile(filepath)
        if audio_only:
            await callback.message.answer_audio(file)
        else:
            await callback.message.answer_video(file)

        await callback.message.edit_text("✅ Tayyor!")

    except DownloadError as e:
        logger.warning(f"Yuklashda xato: {e}")
        await callback.message.edit_text(
            "❌ Video yuklab bo'lmadi. Link noto'g'ri, private akkaunt "
            "yoki video o'chirilgan bo'lishi mumkin."
        )
    except Exception as e:
        logger.exception("Kutilmagan xato")
        await callback.message.edit_text("❌ Nimadir xato ketdi. Keyinroq urinib ko'ring.")
    finally:
        cleanup_file(filepath)
        _last_url.pop(user_id, None)
