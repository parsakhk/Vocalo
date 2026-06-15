from telegram import Update, Chat
from telegram.ext import ContextTypes
from db.queries import enable_group, is_group_enabled, get_or_create_user


async def enable_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    # /enable must be used inside a group or supergroup
    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.message.reply_text(
            "⚠️ `/enable` فقط توی یک گروه میتونه اجرا شه.",
            parse_mode="Markdown",
        )
        return

    # Make sure the user calling /enable exists in our DB
    get_or_create_user(
        telegram_id=user.id,
        full_name=user.full_name,
        username=user.username,
    )

    if is_group_enabled(chat.id):
        await update.message.reply_text(
            "✅ اسپاون کردن کارکتر ها از قبل در این گروه فعال شده است",
            parse_mode="Markdown",
        )
        return

    enable_group(
        group_id=chat.id,
        group_name=chat.title or "Unknown Group",
        enabled_by=user.id,
    )

    await update.message.reply_text(
        "🎉 *ووکالو در این گروه فعال شد!*\n\n"
        "کارکتر ها هنگامی که گروه فعال بشه ظاهر خواهند شد 🔥\n",
        parse_mode="Markdown",
    )