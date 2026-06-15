from telegram import Update, Chat
from telegram.ext import ContextTypes
from db.queries import is_group_enabled, get_or_create_user
from handlers.enable import _cancel_spawn_job


async def disable_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.message.reply_text(
            "⚠️ `/disable` فقط توی گروه میتونی استفاده کنی.",
            parse_mode="Markdown",
        )
        return

    get_or_create_user(user.id, user.full_name, user.username)

    if not is_group_enabled(chat.id):
        await update.message.reply_text(
            "⚠️ اصن از قبل اینجا چیزی فعال نبود.",
            parse_mode="Markdown",
        )
        return

    # Cancel the repeating spawn job
    _cancel_spawn_job(context, chat.id)

    # Remove from DB
    from db.client import get_db
    get_db().table("enabled_groups").delete().eq("group_id", chat.id).execute()

    await update.message.reply_text(
        "🔴 *ووکالو در این گروه غیر فعال شد.*\n\n"
        "دیگه هیچ کارکتری اسپاون نمیشه. از دستور  /enable استفاده کن تا برگرده.",
        parse_mode="Markdown",
    )