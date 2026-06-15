from telegram import Update
from telegram.ext import ContextTypes
from db.queries import get_or_create_user


async def signin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return

    _, created = get_or_create_user(
        telegram_id=user.id,
        full_name=user.full_name,
        username=user.username,
    )

    if created:
        await update.message.reply_text(
            f"✅ *{user.first_name}* you're now registered in Anime Catch!\n\n"
            "You can start catching characters in this group 🎴\n"
            "Use /profile to see your stats and /inventory to see your collection.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"👋 *{user.first_name}*, you're already registered!\n\n"
            "Use /profile to see your stats.",
            parse_mode="Markdown",
        )