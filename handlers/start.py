from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Salom! 👋 Men <b>TopBot</b>man.\n\n"
        "Menga Instagram, TikTok, YouTube, Facebook yoki Twitter/X "
        "linkini yuboring — videoni yoki audioni yuklab beraman.\n\n"
        "Buyruqlar:\n"
        "/help — yordam"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📌 <b>Qanday ishlataman?</b>\n\n"
        "1. Instagram, TikTok, YouTube va h.k. dan video linkini nusxalang\n"
        "2. Shu linkni menga yuboring\n"
        "3. Men videoni yuklab, sizga qaytaraman\n\n"
        "Faqat audio (mp3) kerak bo'lsa, video yuborilgach chiqadigan "
        "tugmalardan foydalaning."
    )
