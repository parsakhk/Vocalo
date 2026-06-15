from telegram import Update, Chat
from telegram.ext import ContextTypes
from db.queries import is_group_enabled, get_active_spawn
from handlers.messages import _spawn_character


async def forcespawn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat    = update.effective_chat
    user    = update.effective_user
    message = update.message

    # Must be used in a group
    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await message.reply_text("⚠️ This command can only be used in a group.")
        return

    # Only allowed for the bot owner
    if user.id != 1678605129:
        await message.reply_text("❌ You don't have permission to use this command.")
        return

    # Group must have the bot enabled
    if not is_group_enabled(chat.id):
        await message.reply_text(
            "⚠️ Anime spawning is not enabled in this group.\n"
            "Use /enable first."
        )
        return

    # Don't spawn if one is already active
    if get_active_spawn(chat.id):
        await message.reply_text("⏳ There's already a character waiting to be caught!")
        return

    # Delete the /forcespawn command message to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass

    spawned = await _spawn_character(update, context, force=True)
    if not spawned:
        await context.bot.send_message(
            chat_id=chat.id,
            text="❌ No characters found in the database."
        )