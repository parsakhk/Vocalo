import logging
from telegram import Update, Chat
from telegram.ext import ContextTypes

from db.queries import (
    is_group_enabled,
    get_active_spawn,
    add_to_inventory,
    get_or_create_user,
    match_character_by_guess,
    rarity_emoji,
)
from db.client import get_db

logger = logging.getLogger(__name__)


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

    # Correct — cancel the expiry job
    for job in context.job_queue.get_jobs_by_name(f"spawn_expire_{chat.id}"):
        job.schedule_removal()

    final_price, rarity = add_to_inventory(
        telegram_id=user.id,
        character_id=character["id"],
        base_price=character["base_price"],
    )

    from db.queries import clear_active_spawn
    clear_active_spawn(chat.id)

    emoji = rarity_emoji(rarity)

    await message.reply_text(
        f"🎉 *{user.first_name}* caught *{character['name']}*!\n\n"
        f"{emoji} Rarity: *{rarity}*\n"
        f"💰 Value: *{final_price} coins* (base {character['base_price']} × multiplier)\n\n"
        f"Added to your inventory! 🗂",
        parse_mode="Markdown",
    )