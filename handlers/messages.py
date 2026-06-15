import logging
from telegram import Update, Chat
from telegram.ext import ContextTypes

from db.queries import (
    is_group_enabled,
    get_random_character,
    get_active_spawn,
    set_active_spawn,
    clear_active_spawn,
    add_to_inventory,
    get_or_create_user,
    match_character_by_guess,
    rarity_emoji,
)
from db.client import get_db
from utils.rate_checker import record_message

logger = logging.getLogger(__name__)

SPAWN_COOLDOWN = 120  # seconds


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat    = update.effective_chat
    user    = update.effective_user
    message = update.message

    if not message or not user or not chat:
        return

    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        return

    if not is_group_enabled(chat.id):
        return

    if message.reply_to_message:
        await _try_catch(update, context)
        return

    if record_message(chat.id):
        await _spawn_character(update, context)


# ── Spawn ─────────────────────────────────────────────────────────────────────

async def _spawn_character(update: Update, context: ContextTypes.DEFAULT_TYPE, force: bool = False) -> bool:
    """
    Spawns a character in the chat.
    Returns True if a spawn was successfully created, False otherwise.
    """
    chat = update.effective_chat

    if get_active_spawn(chat.id):
        return False

    character = get_random_character()
    if not character:
        logger.warning("No characters in the database to spawn.")
        return False

    try:
        sent = await context.bot.send_photo(
            chat_id=chat.id,
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
        logger.error("Failed to send spawn photo: %s", e)
        return False

    set_active_spawn(
        group_id=chat.id,
        character_id=character["id"],
        message_id=sent.message_id,
    )

    # Schedule the "escaped" message after 2 minutes
    context.job_queue.run_once(
        _spawn_expired,
        when=SPAWN_COOLDOWN,
        data={
            "chat_id":    chat.id,
            "message_id": sent.message_id,
        },
        name=f"spawn_expire_{chat.id}",
    )

    return True


async def _spawn_expired(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called by job queue after cooldown — clears spawn and sends escaped message."""
    data       = context.job.data
    chat_id    = data["chat_id"]
    message_id = data["message_id"]

    spawn = get_active_spawn(chat_id)

    # If spawn was already caught, do nothing
    if not spawn or spawn["message_id"] != message_id:
        return

    clear_active_spawn(chat_id)

    await context.bot.send_message(
        chat_id=chat_id,
        text="ای بابا اینم که در رفت 😮‍💨",
        reply_to_message_id=message_id,
    )


# ── Catch ─────────────────────────────────────────────────────────────────────

async def _try_catch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat    = update.effective_chat
    user    = update.effective_user
    message = update.message

    spawn = get_active_spawn(chat.id)
    if not spawn:
        return

    if message.reply_to_message.message_id != spawn["message_id"]:
        return

    get_or_create_user(
        telegram_id=user.id,
        full_name=user.full_name,
        username=user.username,
    )

    guess = (message.text or "").strip()

    db = get_db()
    char_res = (
        db.table("characters")
        .select("*")
        .eq("id", spawn["character_id"])
        .execute()
    )
    if not char_res.data:
        return

    character = char_res.data[0]

    if not match_character_by_guess(guess, character):
        await message.reply_text(
            "❌ That's not right! Keep trying — someone else might catch them first!"
        )
        return

    # Correct guess — cancel the expiry job first
    current_jobs = context.job_queue.get_jobs_by_name(f"spawn_expire_{chat.id}")
    for job in current_jobs:
        job.schedule_removal()

    final_price, rarity = add_to_inventory(
        telegram_id=user.id,
        character_id=character["id"],
        base_price=character["base_price"],
    )
    clear_active_spawn(chat.id)

    emoji = rarity_emoji(rarity)

    await message.reply_text(
        f"🎉 *{user.first_name}* caught *{character['name']}*!\n\n"
        f"{emoji} Rarity: *{rarity}*\n"
        f"💰 Value: *{final_price} coins* (base {character['base_price']} × multiplier)\n\n"
        f"Added to your inventory! 🗂",
        parse_mode="Markdown",
    )