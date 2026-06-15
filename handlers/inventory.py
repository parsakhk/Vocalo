from telegram import Update
from telegram.ext import ContextTypes
from db.queries import get_inventory, get_or_create_user, format_inventory


async def inventory_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return

    get_or_create_user(user.id, user.full_name, user.username)
    items = get_inventory(user.id)

    if not items:
        await update.message.reply_text(
            "🗂 اینونتوریت *خالیه*!\n\n"
            "برو توی یک گروه فعال کارکترای مخلتفو صید کن 🎴",
            parse_mode="Markdown",
        )
        return

    text = format_inventory(items, user.first_name)
    await update.message.reply_text(text, parse_mode="Markdown")