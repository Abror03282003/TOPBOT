from aiogram import Router, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from database import add_user, process_referral, get_contest_settings, get_top3_leaderboard

router = Router()

def get_contest_post_keyboard(bot_username: str, user_id: int):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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

@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, bot: Bot):
    user_id = message.from_user.id
    full_name = message.from_user.full_name
    username = message.from_user.username or ""

    # 1. Foydalanuvchini bazaga qo'shish
    await add_user(user_id, full_name, username)

    # 2. Referal havolasini tekshirish
    args = command.args
    if args:
        referrer_id = None
        if args.startswith("ref_"):
            try:
                referrer_id = int(args.replace("ref_", ""))
            except ValueError:
                pass
        elif args.isdigit():
            referrer_id = int(args)

        if referrer_id and referrer_id != user_id:
            is_new = await process_referral(new_user_id=user_id, referrer_id=referrer_id)
            if is_new:
                try:
                    await bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 <b>Yangi taklif!</b>\n\n<b>{full_name}</b> sizning havolangiz orqali botga kirdi! +1 referal taqdim etildi.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

    # 3. Salomlashuv xabari
    await message.answer(
        "Salom! 👋 Men <b>TopBot</b>man.\n\n"
        "Menga Instagram, TikTok, YouTube, Facebook yoki Twitter/X "
        "linkini yuboring — videoni yoki audioni yuklab beraman.\n\n"
        "Buyruqlar:\n"
        "/help — yordam\n"
        "/contest — konkurs va reyting",
        parse_mode="HTML"
    )

    # 4. Faol konkurs bo'lsa, post yuborish
    contest = await get_contest_settings()
    if contest and contest.get("is_active"):
        bot_info = await bot.get_me()
        top3 = await get_top3_leaderboard()
        
        top3_text = "\n"
        medals = ["🥇", "🥈", "🥉"]
        if top3:
            for idx, (name, count) in enumerate(top3):
                top3_text += f"{medals[idx]} <b>{name}</b> — {count} ta referal\n"
        else:
            top3_text += "<i>Hali hech kim referal to'plamadi. Birinchi bo'ling!</i>\n"

        post_text = contest.get("post_text") or "🔥 DAXSHAT KONKURS BOSHLANDI!"
        final_caption = (
            f"{post_text}\n\n"
            f"🎯 <b>Maqsad:</b> {contest['target']} ta do'stni taklif qilish\n"
            f"💰 <b>Mukofot:</b> {contest['prize']:,} so'm\n"
            f"⏳ <b>Tugash vaqti:</b> {contest['end_time'] or 'Tez orada'}\n\n"
            f"🏆 <b>Hozirgi TOP-3 Yetakchilar:</b>\n"
            f"{top3_text}"
        )
        
        reply_kb = get_contest_post_keyboard(bot_info.username, user_id)
        photo_id = contest.get("photo_id")

        try:
            if photo_id:
                await message.answer_photo(photo=photo_id, caption=final_caption, reply_markup=reply_kb, parse_mode="HTML")
            else:
                await message.answer(text=final_caption, reply_markup=reply_kb, parse_mode="HTML")
        except Exception:
            pass

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📌 <b>Qanday ishlataman?</b>\n\n"
        "1. Qo'shiq nomini yoki ijrochini yozib yuboring (Masalan: <i>Shoxrux Xatuba</i>)\n"
        "2. Yoki Instagram, TikTok, YouTube linkini yuboring\n"
        "3. Ovozli xabar (voice) yoki video-xabar yuborsangiz, Shazam orqali musiqa topib beraman!",
        parse_mode="HTML"
    )
