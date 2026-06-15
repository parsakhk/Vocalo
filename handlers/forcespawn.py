from telegram import Update, Chat
from telegram.ext import ContextTypes
from db.queries import is_group_enabled, get_active_spawn
from handlers.enable import _auto_spawn


async def forcespawn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat    = update.effective_chat
    user    = update.effective_user
    message = update.message

    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await message.reply_text("⚠️ This command can only be used in a group.")
        return

    if user.id != 1678605129:
        await message.reply_text("❌ You don't have permission to use this command.")
        return

    if not is_group_enabled(chat.id):
        await message.reply_text(
            "⚠️ Anime spawning is not enabled in this group.\nUse /enable first."
        )
        return

    if get_active_spawn(chat.id):
        await message.reply_text("⏳ There's already a character waiting to be caught!")
        return

    try:
        await message.delete()
    except Exception:
        pass

    # Reuse the same auto spawn logic
    context.job.data = {"chat_id": chat.id}
    await _auto_spawn(context)