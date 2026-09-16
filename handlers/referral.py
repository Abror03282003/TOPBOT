from aiogram import Router, F
from aiogram.types import Message
from database import get_contest_settings, get_leaderboard, aiosqlite, DB_NAME

router = Router()

@router.message(F.text == "🏆 Konkurs va Reyting")
async def show_contest(message: Message):
    contest = await get_contest_settings()
    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"

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
