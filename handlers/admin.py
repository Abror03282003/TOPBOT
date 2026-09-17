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
    get_winner,
    get_top3_leaderboard,
    update_contest_announcement
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
    waiting_for_post_content = State()

# --- TUGMALAR YARATISH FUNKSIYALARI ---

def admin_contest_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="➕ Yangi konkurs boshlash", callback_data="admin_start_contest")],
        [InlineKeyboardButton(text="🛑 Konkursni to'xtatish", callback_data="admin_stop_contest")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_contest_post_keyboard(bot_username: str, user_id: int):
    """Foydalanuvchilarga boradigan post ostidagi shaxsiy tugmalar."""
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    share_url = f"https://t.me/share/url?url={ref_link}&text=🚀%20Botda%20daxshat%20konkurs%20boshlandi!%20Qatnashib%20pul%20yutib%20oling!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📲 Postni ulashish", url=share_url),
            InlineKeyboardButton(text="🔗 Linkimni olish", callback_data="get_my_ref_link")
        ],
        [
            InlineKeyboardButton(text="📊 Reyting va Natijalar", callback_data="check_leaderboard")
        ]
    ])
    return keyboard

# --- STATISTIKA VA REKLAMA ---

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
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await message.answer(
        f"✅ <b>Xabar yuborildi!</b>\n\n"
        f"Muvaffaqiyatli: <b>{success}</b>\n"
        f"Muvaffaqiyatsiz (bloklaganlar): <b>{failed}</b>", 
        parse_mode="HTML"
    )

# --- KONKURS BOSHGARUVI ---

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
async def process_duration(message: Message, state: FSMContext):
    try:
        hours = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer("❌ Iltimos, soatni raqamda kiriting (masalan: 2 yoki 4.5):")
        return

    await state.update_data(hours=hours)
    await state.set_state(ContestState.waiting_for_post_content)
    await message.answer(
        "📝 <b>Endi foydalanuvchilarga boradigan konkurs posti (matn va rasm)ni yuboring:</b>\n\n"
        "<i>(Ajoyib matn va rasm yuborsangiz bo'ladi. Matnsiz rasm yoki shunchaki matn yuborish ham mumkin)</i>",
        parse_mode="HTML"
    )

@router.message(ContestState.waiting_for_post_content, F.from_user.id == ADMIN_ID)
async def process_post_content(message: Message, state: FSMContext, bot: Bot):
    """Admin yuborgan postni qabul qilish, bazaga saqlash va barcha foydalanuvchilarga tarqatish."""
    data = await state.get_data()
    target = data['target']
    prize = data['prize']
    hours = data['hours']

    end_dt = datetime.now() + timedelta(hours=hours)
    end_time_str = end_dt.strftime("%Y-%m-%d %H:%M")

    post_text = message.caption or message.text or "🔥 DAXSHAT KONKURS BOSHLANDI!"
    photo_id = message.photo[-1].file_id if message.photo else None

    await update_contest_announcement(target, prize, end_time_str, post_text, photo_id)
    await state.clear()

    bot_info = await bot.get_me()
    bot_username = bot_info.username

    top3 = await get_top3_leaderboard()
    top3_text = "\n"
    medals = ["🥇", "🥈", "🥉"]
    if top3:
        for idx, (name, count) in enumerate(top3):
            top3_text += f"{medals[idx]} <b>{name}</b> — {count} ta referal\n"
    else:
        top3_text += "<i>Hali hech kim referal to'plamadi. Birinchi bo'ling!</i>\n"

    await message.answer("🚀 <b>Konkurs boshlandi va barcha foydalanuvchilarga shaxsiy linklari bilan yuborilmoqda...</b>", parse_mode="HTML")

    users = await get_all_user_ids()
    success = 0

    for u_id in users:
        final_caption = (
            f"{post_text}\n\n"
            f"🎯 <b>Maqsad:</b> {target} ta do'stni taklif qilish\n"
            f"💰 <b>Mukofot:</b> {prize:,} so'm\n"
            f"⏳ <b>Tugash vaqti:</b> {end_time_str}\n\n"
            f"🏆 <b>Hozirgi TOP-3 Yetakchilar:</b>\n"
            f"{top3_text}"
        )
        reply_kb = get_contest_post_keyboard(bot_username, u_id)
        try:
            if photo_id:
                await bot.send_photo(chat_id=u_id, photo=photo_id, caption=final_caption, reply_markup=reply_kb, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=u_id, text=final_caption, reply_markup=reply_kb, parse_mode="HTML")
            
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass

    await message.answer(
        f"✅ <b>Konkurs muvaffaqiyatli yoqildi va e'lon yuborildi!</b>\n\n"
        f"📢 Yuborildi: <b>{success} ta</b> foydalanuvchiga",
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

        try:
            await bot.send_message(
                chat_id=ADMIN_ID, 
                text=f"🔔 <b>[ADMIN BILDIRISHNOMA]</b> Konkurs vaqti tugadi!\n\n{announce_text}", 
                parse_mode="HTML"
            )
        except Exception:
            pass

        all_users = await get_all_user_ids()
        for user_id in all_users:
            try:
                await bot.send_message(chat_id=user_id, text=announce_text, parse_mode="HTML")
                await asyncio.sleep(0.05)
            except Exception:
                pass

@router.callback_query(F.data == "admin_stop_contest", F.from_user.id == ADMIN_ID)
async def stop_contest_callback(call: CallbackQuery, bot: Bot):
    """Konkursni admin tomonidan muddatidan oldin to'xtatish."""
    contest = await get_contest_settings()

    if not contest["is_active"]:
        await call.answer("⚠️ Hozirda hech qanday faol konkurs yo'q!", show_alert=True)
        return

    await stop_contest_db()
    winner = await get_winner()

    if winner and winner[2] > 0:
        winner_id, full_name, count = winner
        announce_text = (
            f"🛑 <b>KONKURS MUDDATIDAN OLDIN YAKUNLANDI!</b>\n\n"
            f"Admin tomonidan konkurs muddatidan oldin to'xtatildi.\n\n"
            f"🏆 <b>Hozirgi g'olib:</b> <a href='tg://user?id={winner_id}'>{full_name}</a>\n"
            f"📊 <b>To'plagan referallari:</b> {count} ta\n"
            f"🎁 <b>Yutug'i:</b> {contest['prize']:,} so'm!\n\n"
            f"👏 G'olibni tabriklaymiz!"
        )
    else:
        announce_text = (
            f"🛑 <b>KONKURS MUDDATIDAN OLDIN YAKUNLANDI!</b>\n\n"
            f"Admin tomonidan konkurs to'xtatildi.\n"
            f"Afsuski, hech kim yetarli referal yig'a olmadi."
        )

    await call.message.edit_text("🔴 <b>Konkurs muddatidan oldin to'xtatildi. Barcha foydalanuvchilarga xabar yuborilmoqda...</b>", parse_mode="HTML")
    await call.answer("Konkurs to'xtatildi")

    all_users = await get_all_user_ids()
    success = 0

    for user_id in all_users:
        try:
            await bot.send_message(chat_id=user_id, text=announce_text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass

    await call.message.answer(f"✅ Konkurs to'xtatilgani haqidagi e'lon <b>{success} ta</b> foydalanuvchiga yetkazildi!", parse_mode="HTML")
