from telegram import Update
from telegram.ext import ContextTypes
from db.queries import get_or_create_user, get_profile_stats
from datetime import datetime


async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return

    db_user, _ = get_or_create_user(user.id, user.full_name, user.username)
    stats = get_profile_stats(user.id)

    # Format join date
    joined_raw = db_user.get("created_at", "")
    try:
        joined = datetime.fromisoformat(joined_raw).strftime("%B %Y")
    except Exception:
        joined = "Unknown"

    coins     = db_user.get("coins", 0)
    total     = stats["total"]
    counts    = stats["rarity_counts"]
    portfolio = stats["portfolio_value"]
    rarest    = stats["rarest_char"]
    fav       = stats["favorite_anime"]

    rarest_text = f"{rarest['name']} ({rarest['rarity']})" if rarest else "None yet"
    fav_text    = fav if fav else "None yet"

    text = (
        f"👤 *Name* — {user.first_name}\n"
        f"\n"
        f"📅 *Joined* : {joined}\n"
        f"💰 *Coins*: {coins:,}\n"
        f"\n"
        f"📦 *Collection* ({total} characters)\n"
        f"╔ 🌟 Legendary  →  {counts.get('Legendary', 0)}\n"
        f"╠ 💜 Mythic     →  {counts.get('Mythic', 0)}\n"
        f"╠ 💙 Rare       →  {counts.get('Rare', 0)}\n"
        f"╚ ⚪ Common     →  {counts.get('Common', 0)}\n"
        f"\n"
        f"💎 *Account Value*: {portfolio:,} coins\n"
        f"🏆 *Rarest Catch*: {rarest_text}\n"
        f"🎌 *Favorite Anime*: {fav_text}"
    )

    await update.message.reply_text(text, parse_mode="Markdown")