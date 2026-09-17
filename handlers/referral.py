from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from database import get_contest_settings, get_leaderboard, get_top3_leaderboard, aiosqlite, DB_NAME

router = Router()

@router.message(F.text == "🏆 Konkurs va Reyting")
async def show_contest(message: Message):
    contest = await get_contest_settings()
    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT referrals_count FROM users WHERE user_id = ?", (message.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            my_refs = row[0] if row else 0

    if not contest["is_active"]:
        await message.answer("⚠️ Hozirda faol konkurs mavjud emas. Yangi konkursni kuting!")
        return

    leaderboard = await get_leaderboard(10)
    board_text = ""
    for idx, (name, count) in enumerate(leaderboard, 1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        board_text += f"{medal} {name} — <b>{count}</b> ta taklif\n"

    text = (
        f"🎁 <b>KONKURS SHARTLARI:</b>\n"
        f"Kim birinchi bo'lib botga <b>{contest['target']} ta</b> do'stini taklif qilsa "
        f"<b>{contest['prize']:,} so'm</b> mukofot oladi!\n\n"
        f"⏳ <b>Tugash vaqti:</b> {contest['end_time']}\n\n"
        f"🔗 <b>Sizning taklif havolangiz:</b>\n<code>{ref_link}</code>\n\n"
        f"📊 <b>Sizning takliflaringiz:</b> {my_refs} / {contest['target']}\n\n"
        f"🏆 <b>ONLAYN REYTING (TOP-10):</b>\n{board_text if board_text else 'Hozircha hech kim taklif qilmadi.'}"
    )

    await message.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "get_my_ref_link")
async def send_user_ref_link(call: CallbackQuery, bot: Bot):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{call.from_user.id}"
    
    text = (
        f"🔑 <b>Sizning shaxsiy taklif havolangiz:</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"💡 Ushbu havolani do'stlaringizga tarqating va konkursda g'olib bo'ling!"
    )
    await call.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    await call.answer()

@router.callback_query(F.data == "check_leaderboard")
async def show_live_leaderboard(call: CallbackQuery):
    top3 = await get_top3_leaderboard()
    contest = await get_contest_settings()

    medals = ["🥇", "🥈", "🥉"]
    top_text = "🏆 <b>Hozirgi TOP-3 Yetakchilar:</b>\n\n"
    if top3:
        for idx, (name, count) in enumerate(top3):
            top_text += f"{medals[idx]} <b>{name}</b> — {count} ta referal\n"
    else:
        top_text += "<i>Hali hech kim referal to'plamadi. Birinchi bo'ling!</i>\n"

    top_text += f"\n🎯 Maqsad: <b>{contest['target']} ta</b> | 💰 Mukofot: <b>{contest['prize']:,} so'm</b>"

    await call.answer(show_alert=True, text="📊 Reyting yangilandi!")
    await call.message.answer(top_text, parse_mode="HTML")
