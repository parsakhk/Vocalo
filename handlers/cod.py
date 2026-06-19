
import random
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.queries import get_or_create_user, roll_rarity, rarity_emoji
from db.client import get_db

PRICE_MULTIPLIER = 1.75
COOLDOWN_HOURS   = 24

RARITY_BONUS = {
    "Common":    0,
    "Rare":      250,
    "Mythic":    500,
    "Legendary": 1000,
}


def _calc_price(base_price: int, rarity: str) -> int:
    return int(base_price * PRICE_MULTIPLIER) + RARITY_BONUS.get(rarity, 0)


async def cod_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    get_or_create_user(user.id, user.full_name, user.username)

    db  = get_db()
    now = datetime.now(timezone.utc)

    # Fetch or create COD record for this group
    res = db.table("cod").select("*").eq("group_id", chat.id).execute()

    if res.data:
        cod = res.data[0]
        last_dt = datetime.fromisoformat(cod["created_at"])
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        next_reset = last_dt + timedelta(hours=COOLDOWN_HOURS)

        # Still within the same 24h window
        if now < next_reset:
            if cod["purchased"]:
                remaining  = next_reset - now
                hours, rem = divmod(int(remaining.total_seconds()), 3600)
                minutes    = rem // 60
                await update.message.reply_text(
                    f"🛒 Today's character has already been purchased!\n\n"
                    f"⏰ Next character of the day in *{hours}h {minutes}m*",
                    parse_mode="Markdown",
                )
                return

            # Still available — show existing COD
            await _show_cod(update, context, cod)
            return

        # 24h passed — delete old record and generate new one
        db.table("cod").delete().eq("group_id", chat.id).execute()

    # Generate new COD
    chars_res = db.table("characters").select("*").execute()
    if not chars_res.data:
        await update.message.reply_text("❌ No characters in the database.")
        return

    character = random.choice(chars_res.data)
    rarity    = roll_rarity()
    attack    = random.randint(character.get("atk_min", 50), character.get("atk_max", 150))
    defense   = random.randint(character.get("def_min", 30), character.get("def_max", 100))
    price     = _calc_price(character["base_price"], rarity)

    db.table("cod").insert({
        "group_id":     chat.id,
        "character_id": character["id"],
        "rarity":       rarity,
        "attack":       attack,
        "defense":      defense,
        "price":        price,
        "purchased":    False,
        "created_at":   now.isoformat(),
    }).execute()

    res = db.table("cod").select("*").eq("group_id", chat.id).execute()
    await _show_cod(update, context, res.data[0])


async def _show_cod(update: Update, context: ContextTypes.DEFAULT_TYPE, cod: dict) -> None:
    db         = get_db()
    char_res   = db.table("characters").select("*").eq("id", cod["character_id"]).execute()
    if not char_res.data:
        await update.message.reply_text("⚠️ Character data not found.")
        return

    character  = char_res.data[0]
    rarity     = cod["rarity"]
    emoji      = rarity_emoji(rarity)
    price      = cod["price"]
    attack     = cod["attack"]
    defense    = cod["defense"]
    cod_id     = cod["id"]

    caption = (
        f"🌟 *Character of the Day!*\n\n"
        f"{emoji} *{character['name']}*\n"
        f"🎌 Anime: *{character['anime']}*\n"
        f"🏅 Rarity: *{rarity}*\n\n"
        f"⚔️ Attack:  *{attack}*\n"
        f"🛡 Defense: *{defense}*\n\n"
        f"💰 Price: *{price:,} VP*\n"
        f"_(base {character['base_price']} × 1.75"
        + (f" + {RARITY_BONUS[rarity]} {rarity} bonus" if RARITY_BONUS.get(rarity) else "")
        + ")_\n\n"
        f"⏰ Available for *24 hours* — first come first served!"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"🛒 Purchase for {price:,} VP",
            callback_data=f"cod_buy:{cod_id}",
        )
    ]])

    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=character["image_url"],
            caption=caption,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception:
        await update.message.reply_text(
            caption,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


async def cod_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user  = update.effective_user
    await query.answer()

    cod_id = int(query.data.split(":")[1])
    get_or_create_user(user.id, user.full_name, user.username)

    db  = get_db()
    res = db.table("cod").select("*").eq("id", cod_id).execute()

    if not res.data:
        await query.edit_message_caption("⚠️ This offer has expired.")
        return

    cod = res.data[0]

    if cod["purchased"]:
        await query.answer("❌ Already purchased by someone else!", show_alert=True)
        return

    # Check balance
    user_res = db.table("users").select("coins").eq("telegram_id", user.id).execute()
    balance  = user_res.data[0]["coins"] if user_res.data else 0

    if balance < cod["price"]:
        await query.answer(
            f"❌ Not enough VP! You have {balance:,} but need {cod['price']:,}.",
            show_alert=True,
        )
        return

    # Mark as purchased
    db.table("cod").update({"purchased": True, "purchased_by": user.id}).eq("id", cod_id).execute()

    # Add to inventory
    db.table("inventory").insert({
        "telegram_id":  user.id,
        "character_id": cod["character_id"],
        "caught_price": cod["price"],
        "rarity":       cod["rarity"],
        "attack":       cod["attack"],
        "defense":      cod["defense"],
    }).execute()

    # Deduct VP
    db.rpc("increment_coins", {"user_id": user.id, "amount": -cod["price"]}).execute()

    # Fetch character name for confirmation
    char_res  = db.table("characters").select("name").eq("id", cod["character_id"]).execute()
    char_name = char_res.data[0]["name"] if char_res.data else "Character"
    emoji     = rarity_emoji(cod["rarity"])

    await query.edit_message_caption(
        f"✅ *{user.first_name}* purchased the Character of the Day!\n\n"
        f"{emoji} *{char_name}* — *{cod['rarity']}*\n"
        f"💰 *{cod['price']:,} VP* spent\n\n"
        f"Added to your inventory! 🎴",
        parse_mode="Markdown",
    )