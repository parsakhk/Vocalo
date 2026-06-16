"""
/bet <amount> — Gamble Vocalo Points.

Win chance starts at 45% and decreases the more you bet.
If you win, you get 1.5x your bet added to your balance.
"""
import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.queries import get_or_create_user
from db.client import get_db

# Base win chance (45%) — reduced by bet size relative to balance
BASE_WIN_CHANCE = 0.45
# Each 10% of balance bet reduces win chance by 3%
CHANCE_REDUCTION_PER_10PCT = 0.03

SUSPENSE_LINES = [
    "🎲 The dice are rolling...",
    "⚡ The fates are deciding...",
    "🌀 The odds are calculating...",
    "🔮 The spirits are consulting...",
]

WIN_LINES = [
    "🎉 Lady luck smiles upon you!",
    "💫 The stars aligned in your favor!",
    "🔥 You're on fire! What a win!",
    "⚡ Lightning strikes — and it's YOURS!",
]

LOSE_LINES = [
    "💀 The house always wins...",
    "😭 Tough luck, better luck next time!",
    "🌧 The odds were never in your favor.",
    "💸 And just like that... it's gone.",
]


def _calc_win_chance(bet: int, balance: int) -> float:
    """Lower win chance the higher the bet is relative to balance."""
    if balance == 0:
        return 0.0
    ratio         = bet / balance          # 0.0 → 1.0
    reductions    = ratio / 0.10           # how many 10% chunks
    reduced_by    = reductions * CHANCE_REDUCTION_PER_10PCT
    chance        = BASE_WIN_CHANCE - reduced_by
    return max(0.05, round(chance, 3))     # never below 5%


async def bet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.full_name, user.username)

    # ── Validate argument ─────────────────────────────────────────────────────
    if not context.args:
        await update.message.reply_text(
            "Usage: `/bet <amount>`\nExample: `/bet 500`",
            parse_mode="Markdown",
        )
        return

    try:
        bet = int(context.args[0].replace(",", ""))
        assert bet > 0
    except (ValueError, AssertionError):
        await update.message.reply_text("⚠️ Please enter a valid positive amount.\nExample: `/bet 500`", parse_mode="Markdown")
        return

    db  = get_db()
    res = db.table("users").select("coins").eq("telegram_id", user.id).execute()
    balance = res.data[0]["coins"] if res.data else 0

    if bet > balance:
        await update.message.reply_text(
            f"❌ You don't have enough VP!\n\n"
            f"💰 Your balance: *{balance:,} VP*\n"
            f"🎲 Your bet: *{bet:,} VP*",
            parse_mode="Markdown",
        )
        return

    if bet < 100:
        await update.message.reply_text("⚠️ Minimum bet is *100 VP*.", parse_mode="Markdown")
        return

    win_chance = _calc_win_chance(bet, balance)
    won        = random.random() < win_chance
    payout     = int(bet * 1.5) if won else 0
    net        = payout - bet   # positive if won, negative if lost

    # ── Suspense message ──────────────────────────────────────────────────────
    suspense_text = (
        f"🎲 *{user.first_name} bets {bet:,} VP!*\n\n"
        f"{random.choice(SUSPENSE_LINES)}\n\n"
        f"⏳ Results in 5 seconds..."
    )
    msg = await update.message.reply_text(suspense_text, parse_mode="Markdown")

    await asyncio.sleep(5)

    # ── Result ────────────────────────────────────────────────────────────────
    if won:
        db.rpc("increment_coins", {"user_id": user.id, "amount": payout}).execute()
        new_balance = balance + payout

        result_text = (
            f"🎲 *Bet Result*\n\n"
            f"{random.choice(WIN_LINES)}\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎯 Bet placed:  *{bet:,} VP*\n"
            f"🏆 You won:     *+{payout:,} VP*\n"
            f"📈 Net gain:    *+{net:,} VP*\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 New balance: *{new_balance:,} VP*"
        )
    else:
        db.rpc("increment_coins", {"user_id": user.id, "amount": -bet}).execute()
        new_balance = balance - bet

        result_text = (
            f"🎲 *Bet Result*\n\n"
            f"{random.choice(LOSE_LINES)}\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎯 Bet placed:  *{bet:,} VP*\n"
            f"💸 You lost:    *-{bet:,} VP*\n"
            f"📉 Net loss:    *-{bet:,} VP*\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 New balance: *{new_balance:,} VP*"
        )

    await msg.edit_text(result_text, parse_mode="Markdown")