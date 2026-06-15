from telegram import Update, Chat
from telegram.ext import ContextTypes
from db.queries import is_group_enabled, get_random_character, get_active_spawn, set_active_spawn


async def forcespawn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    message = update.message

    # Must be used in a group
    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await message.reply_text("⚠️ این کامند فقط توی گروه میتونه استفاده بشه.")
        return

    # Only allowed for the bot owner
    if user.id != 1678605129:
        await message.reply_text("❌ تو دسترسی به انجام این کامند نداری.")
        return

    # Group must have the bot enabled
    if not is_group_enabled(chat.id):
        await message.reply_text(
            "⚠️ اسپاون کردن کارکترا تو این گروه فعال نشده.\n"
            "Use /enable first."
        )
        return

    # Don't spawn if one is already active
    if get_active_spawn(chat.id):
        await message.reply_text("⏳ قرمساق هنوز کارکتر قبلی گرفته نشده!")
        return

    character = get_random_character()
    if not character:
        await message.reply_text("❌ No characters found in the database.")
        return

    try:
        sent = await context.bot.send_photo(
            chat_id=chat.id,
            photo=character["image_url"],
            caption=(
                f"✨ *A wild anime character has appeared!*\n\n"
                f"🎴 From: *{character['anime']}*\n\n"
                "👉 *Reply to this message* with the character's name to catch them!"
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        await message.reply_text(f"❌ Failed to send character image: {e}")
        return

    set_active_spawn(
        group_id=chat.id,
        character_id=character["id"],
        message_id=sent.message_id,
    )

    # Delete the /forcespawn command message to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass  # bot might not have delete permissions, that's fine