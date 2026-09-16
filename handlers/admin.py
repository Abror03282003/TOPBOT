import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import (
    get_total_users, 
    get_today_active_users, 
    get_all_user_ids,
    get_contest_settings,
    update_contest_settings,
    stop_contest_db,
    get_winner
)

router = Router()

# ⚠️ Telegram ID-ingiz
ADMIN_ID = 1350101870  

class BroadcastState(StatesGroup):
    waiting_for_message = State()

class ContestState(StatesGroup):
    waiting_for_target = State()
    waiting_for_prize = State()
    waiting_for_duration = State()

# --- ESKI FUNKSIYALAR (TEGILMADI) ---

@router.message(Command("stat"), F.from_user.id == ADMIN_ID)
async def cmd_stat(message: Message):
    """Foydalanuvchilar va bugungi faollik statistikasi."""
    total = await get_total_users()
    today_active = await get_today_active_users()
    
    text = (
        "📊 <b>Bot statistikasi:</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total}</b> ta\n"
        f"⚡ Bugun faol foydalanuvchilar: <b>{today_active}</b> ta"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("send"), F.from_user.id == ADMIN_ID)
async def cmd_send(message: Message, state: FSMContext):
    """Barcha foydalanuvchilarga xabar yuborish jarayonini boshlash."""
    await state.set_state(BroadcastState.waiting_for_message)
    await message.answer("📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring (Matn, rasm yoki video):")

@router.message(BroadcastState.waiting_for_message, F.from_user.id == ADMIN_ID)
async def process_broadcast(message: Message, state: FSMContext):
    """Xabarni barchaga tarqatish."""
    await state.clear()
    users = await get_all_user_ids()
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

    await message.answer(
        f"✅ <b>Xabar yuborildi!</b>\n\n"
        f"Muvaffaqiyatli: <b>{success}</b>\n"
        f"Muvaffaqiyatsiz (bloklaganlar): <b>{failed}</b>", 
        parse_mode="HTML"
    )

# --- YANGI KONKURS FUNKSIYALARI ---

def admin_contest_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="➕ Yangi konkurs boshlash", callback_data="admin_start_contest")],
        [InlineKeyboardButton(text="🛑 Konkursni to'xtatish", callback_data="admin_stop_contest")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_panel(message: Message):
    """Admin panel orqali konkurs holatini ko'rish."""
    contest = await get_contest_settings()
    status = "🟢 Faol" if contest["is_active"] else "🔴 To'xtatilgan"
    
    text = (
        f"⚙️ <b>ADMIN KONKURS PANEL</b>\n\n"
        f"<b>Holati:</b> {status}\n"
        f"<b>Maqsad:</b> {contest['target']} ta referal\n"
        f"<b>Mukofot:</b> {contest['prize']:,} so'm\n"
        f"<b>Tugash vaqti:</b> {contest['end_time'] or 'Belgilanmagan'}"
    )
    await message.answer(text, reply_markup=admin_contest_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "admin_start_contest", F.from_user.id == ADMIN_ID)
async def start_contest_flow(call: CallbackQuery, state: FSMContext):
    await call.message.answer("🎯 Konkurs uchun kerakli <b>referal sonini</b> kiriting (masalan: 25):", parse_mode="HTML")
    await state.set_state(ContestState.waiting_for_target)
    await call.answer()

@router.message(ContestState.waiting_for_target, F.from_user.id == ADMIN_ID)
async def process_target(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Iltimos, faqat musbat raqam kiriting!")
        return
    await state.update_data(target=int(message.text))
    await message.answer("💰 <b>Mukofot summasini</b> kiriting (so'mda, masalan: 50000):", parse_mode="HTML")
    await state.set_state(ContestState.waiting_for_prize)

@router.message(ContestState.waiting_for_prize, F.from_user.id == ADMIN_ID)
async def process_prize(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Iltimos, faqat raqam kiriting!")
        return
    await state.update_data(prize=int(message.text))
    
    await message.answer(
        "⏰ Konkurs qancha <b>soat</b> davom etsin?\n"
        "<i>(Masalan: 4 soat bo'lsa, <b>4</b> deb yozing)</i>", 
        parse_mode="HTML"
    )
    await state.set_state(ContestState.waiting_for_duration)

@router.message(ContestState.waiting_for_duration, F.from_user.id == ADMIN_ID)
async def process_duration(message: Message, state: FSMContext, bot: Bot):
    try:
        hours = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer("❌ Iltimos, soatni raqamda kiriting (masalan: 2 yoki 4.5):")
        return

    data = await state.get_data()
    target = data['target']
    prize = data['prize']
    
    end_dt = datetime.now() + timedelta(hours=hours)
    end_time_str = end_dt.strftime("%Y-%m-%d %H:%M")

    await update_contest_settings(target=target, prize=prize, end_time=end_time_str, is_active=1)
    await state.clear()

    await message.answer(
        f"✅ <b>Konkurs muvaffaqiyatli yoqildi!</b>\n\n"
        f"🎯 Odam limiti: <b>{target} ta</b>\n"
        f"💰 Mukofot: <b>{prize:,} so'm</b>\n"
        f"⏳ Tugash vaqti: <b>{end_time_str}</b> ({hours} soatdan so'ng)",
        parse_mode="HTML"
    )

    seconds_to_wait = int(hours * 3600)
    asyncio.create_task(auto_finish_contest(seconds_to_wait, bot))

async def auto_finish_contest(wait_seconds: int, bot: Bot):
    """Vaqt tugaganda konkursni yopib, HAM ADMINGA, HAM BUTUN BOTGA xabar yuborish."""
    await asyncio.sleep(wait_seconds)
    
    contest = await get_contest_settings()
    if contest["is_active"]:
        await stop_contest_db()
        winner = await get_winner()

        if winner and winner[2] > 0:
            winner_id, full_name, count = winner
            announce_text = (
                f"🎉 <b>KONKURS YAKUNLANDI!</b>\n\n"
                f"⏰ Belgilangan vaqt o'z nihoyasiga yetdi.\n\n"
                f"🏆 <b>G'olibimiz:</b> <a href='tg://user?id={winner_id}'>{full_name}</a>\n"
                f"📊 <b>To'plagan referallari:</b> {count} ta\n"
                f"🎁 <b>Yutug'i:</b> {contest['prize']:,} so'm!\n\n"
                f"👏 Tabriklaymiz! G'olib adminga murojaat qilib mukofotini olishi mumkin.\n"
                f"🚀 Keyingi konkurslarimizni kuzatib boring!"
            )
        else:
            announce_text = (
                f"⏰ <b>KONKURS YAKUNLANDI!</b>\n\n"
                f"Afsuski, belgilangan vaqt ichida hech kim g'olib bo'la olmadi.\n\n"
                f"🔥 Tez orada yangi konkurs e'lon qilinadi!"
            )

        # 1. Adminga bildirishnoma yuborish
        try:
            await bot.send_message(
                chat_id=ADMIN_ID, 
                text=f"🔔 <b>[ADMIN BILDIRISHNOMA]</b> Konkurs vaqti tugadi!\n\n{announce_text}", 
                parse_mode="HTML"
            )
        except Exception:
            pass

        # 2. Butun bot foydalanuvchilariga e'lon yuborish
        all_users = await get_all_user_ids()
        for user_id in all_users:
            try:
                await bot.send_message(chat_id=user_id, text=announce_text, parse_mode="HTML")
                await asyncio.sleep(0.05)
            except Exception:
                pass

@router.callback_query(F.data == "admin_stop_contest", F.from_user.id == ADMIN_ID)
async def stop_contest_callback(call: CallbackQuery):
    await stop_contest_db()
    await call.message.edit_text("🔴 Konkurs muddatdan oldin to'xtatildi.")
    await call.answer("Konkurs to'xtatildi")
