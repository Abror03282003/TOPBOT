import asyncio
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import get_total_users, get_all_user_ids

router = Router()

# ⚠️ O'zingizning Telegram ID-ingizni yozing
ADMIN_ID = 1350101870  

class BroadcastState(StatesGroup):
    waiting_for_message = State()

@router.message(Command("stat"), F.from_user.id == ADMIN_ID)
async def cmd_stat(message: Message):
    """Foydalanuvchilar statistikasini ko'rsatish."""
    total = get_total_users()
    await message.answer(f"📊 <b>Bot statistikasi:</b>\n\nJami foydalanuvchilar: <b>{total}</b> ta", parse_mode="HTML")

@router.message(Command("send"), F.from_user.id == ADMIN_ID)
async def cmd_send(message: Message, state: FSMContext):
    """Barcha foydalanuvchilarga xabar yuborish jarayonini boshlash."""
    await state.set_state(BroadcastState.waiting_for_message)
    await message.answer("📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring (Matn, rasm yoki video):")

@router.message(BroadcastState.waiting_for_message, F.from_user.id == ADMIN_ID)
async def process_broadcast(message: Message, state: FSMContext):
    """Xabarni barchaga tarqatish."""
    await state.clear()
    users = get_all_user_ids()
    await message.answer(f"⏳ Xabar {len(users)} ta foydalanuvchiga yuborilmoqda...")

    success = 0
    failed = 0

    for user_id in users:
        try:
            await message.copy_to(chat_id=user_id)
            success += 1
            await asyncio.sleep(0.05)  # Telegram limitidan oshmaslik uchun
        except Exception:
            failed += 1

    await message.answer(f"✅ <b>Xabar yuborildi!</b>\n\nMuvaffaqiyatli: <b>{success}</b>\nMuvaffaqiyatsiz: <b>{failed}</b>", parse_mode="HTML")
