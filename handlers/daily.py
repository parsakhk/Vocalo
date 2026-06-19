"""
/getvocalos — Claim a random amount of Vocalo Points (200–500).
Has a 6 hour cooldown per user.
"""
import random
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from db.queries import get_or_create_user
from db.client import get_db

COOLDOWN_HOURS = 6
MIN_VP         = 200
MAX_VP         = 500


async def getvocalos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.full_name, user.username)

    db  = get_db()
    now = datetime.now(timezone.utc)

    # Check last claim time
    res = db.table("users").select("last_daily, coins").eq("telegram_id", user.id).execute()
    if not res.data:
        await update.message.reply_text("⚠️ Please /signin first.")
        return

    row        = res.data[0]
    last_daily = row.get("last_daily")

    if last_daily:
        last_dt   = datetime.fromisoformat(last_daily)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        next_claim = last_dt + timedelta(hours=COOLDOWN_HOURS)

        if now < next_claim:
            remaining  = next_claim - now
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes    = rem // 60
            await update.message.reply_text(
                f"⏳ You already claimed your Vocalo Points!\n\n"
                f"Come back in *{hours}h {minutes}m* ⌛",
                parse_mode="Markdown",
            )
            return

    # Roll the reward
    amount = random.randint(MIN_VP, MAX_VP)

    # Update coins and last_daily
    db.table("users").update({
        "last_daily": now.isoformat(),
    }).eq("telegram_id", user.id).execute()

    db.rpc("increment_coins", {"user_id": user.id, "amount": amount}).execute()

    new_balance = row["coins"] + amount

    await update.message.reply_text(
        f"🎁 *{user.first_name}* claimed their Vocalo Points!\n\n"
        f"💰 *+{amount} VP* added to your balance!\n"
        f"👛 New balance: *{new_balance:,} VP*\n\n"
        f"⏰ Come back in *{COOLDOWN_HOURS} hours* for more!",
        parse_mode="Markdown",
    )