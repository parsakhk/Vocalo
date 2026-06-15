from telegram import Update, Chat
from telegram.ext import ContextTypes
from db.queries import enable_group, is_group_enabled, get_or_create_user

SPAWN_INTERVAL = 900  # 30 minutes in seconds


async def enable_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.message.reply_text(
            "⚠️ `/enable` can only be used inside a group chat.",
            parse_mode="Markdown",
        )
        return

    get_or_create_user(
        telegram_id=user.id,
        full_name=user.full_name,
        username=user.username,
    )

    # Cancel any existing spawn job for this group first
    _cancel_spawn_job(context, chat.id)

    if not is_group_enabled(chat.id):
        enable_group(
            group_id=chat.id,
            group_name=chat.title or "Unknown Group",
            enabled_by=user.id,
        )

    # Schedule repeating spawn every 30 minutes
    context.job_queue.run_repeating(
        _auto_spawn,
        interval=SPAWN_INTERVAL,
        first=SPAWN_INTERVAL,      # first spawn after 30 minutes
        data={"chat_id": chat.id},
        name=f"auto_spawn_{chat.id}",
    )

    await update.message.reply_text(
        "🎉 *Vocalo is now enabled in this group!*\n\n"
        "⏰ A character will appear every *15 minutes*!\n"
        "Reply with their name to catch them! 🎴",
        parse_mode="Markdown",
    )


def _cancel_spawn_job(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Remove any existing auto_spawn job for this group."""
    for job in context.job_queue.get_jobs_by_name(f"auto_spawn_{chat_id}"):
        job.schedule_removal()


async def _auto_spawn(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job that fires every 30 minutes to spawn a character."""
    from db.queries import get_random_character, get_active_spawn, set_active_spawn

    chat_id = context.job.data["chat_id"]

    # Skip if a character is still waiting to be caught
    if get_active_spawn(chat_id):
        return

    character = get_random_character()
    if not character:
        return

    try:
        sent = await context.bot.send_photo(
            chat_id=chat_id,
            photo=character["image_url"],
            caption=(
                f"✨ *A wild anime character has appeared!*\n\n"
                f"🎴 From: *{character['anime']}*\n\n"
                "👉 *Reply to this message* with the character's name to catch them!\n"
                "_You can use their first or last name too._"
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        from telegram.error import Forbidden
        if isinstance(e, Forbidden):
            # Bot was removed from group — cancel the job
            _cancel_spawn_job(context, chat_id)
        return

    set_active_spawn(
        group_id=chat_id,
        character_id=character["id"],
        message_id=sent.message_id,
    )

    # Schedule the "escaped" message after 2 minutes if nobody catches it
    context.job_queue.run_once(
        _spawn_expired,
        when=120,
        data={"chat_id": chat_id, "message_id": sent.message_id},
        name=f"spawn_expire_{chat_id}",
    )


async def _spawn_expired(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called after 2 minutes if nobody caught the character."""
    from db.queries import get_active_spawn, clear_active_spawn

    data       = context.job.data
    chat_id    = data["chat_id"]
    message_id = data["message_id"]

    spawn = get_active_spawn(chat_id)
    if not spawn or spawn["message_id"] != message_id:
        return

    clear_active_spawn(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text="ای بابا اینم که در رفت 😮‍💨",
        reply_to_message_id=message_id,
    )