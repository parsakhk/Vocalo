from telegram import Update, Chat, ChatMember
from telegram.ext import ContextTypes
from db.queries import is_group_enabled, get_random_character, get_active_spawn, set_active_spawn


async def forcespawn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    message = update.message

    # Must be used in a group
    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await message.reply_text("⚠️ این کامند فقط توی یک گروه امکان پذیر است که انجام شود.")
        return

    # Must be an admin or creator
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in (ChatMember.ADMINISTRATOR, ChatMember.OWNER):
        await message.reply_text("❌ فقط ادمین ها از این کامند میتوانند استفاده کنند.")
        return

    # Group must have the bot enabled
    if not is_group_enabled(chat.id):
        await message.reply_text(
            "⚠️ اسپاون کردن کارکتر در این گروه فعال نشده است.\n"
            "از کامند /enable استفاده کنید"
        )
        return

    # Don't spawn if one is already active
    if get_active_spawn(chat.id):
        await message.reply_text("⏳ هنوز یه کارکتر هست که مونده تا گرفته بشه!")
        return

    character = get_random_character()
    if not character:
        await message.reply_text("❌ این کارکتر موجود نمیباشد.")
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