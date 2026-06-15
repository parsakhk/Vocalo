from telegram import Update
from telegram.ext import ContextTypes
from db.queries import get_or_create_user


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return

    _, created = get_or_create_user(
        telegram_id=user.id,
        full_name=user.full_name,
        username=user.username,
    )

    bot_username = context.bot.username
    invite_link = f"https://t.me/{bot_username}?startgroup=enable"

    if created:
        greeting = (
            f"👋 خوش اومدی, *{user.first_name}*!\n\n"
            "تو در بات ووکالو رجیستر شدی. ✨\n\n"
            "📋 *چطور بازیش کنم:*\n"
            "• من رو به یه گروه اضافه کن و دستور `/enable` رو اونجا بزن\n"
            "• هر نیم ساعت من یه کارکتر انیمه ای توی گروهتون اسپاون میکنم! 🎴\n"
            "• اسم کارکتر رو به پیام بات ریپلای کن تا بگیریش!\n"
            "• هر باری که یه کارکتر رو میگیری قیمتش یک یا یک و نیم برابر زیاد میشه!\n\n"
            f"👉 [منو عضو گروه کن]({invite_link})"
        )
    else:
        greeting = (
            f"خوش اومدی, *{user.first_name}*! 🎌\n\n"
            f"👉 [منو به گروه اضافه کن]({invite_link}) تا شروع کنی به صید کردن"
        )

    await update.message.reply_text(greeting, parse_mode="Markdown")