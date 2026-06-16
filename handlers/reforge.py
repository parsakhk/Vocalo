"""
/reforge — Upgrade a character's rarity by spending Vocalo Points.

Common  →  Rare      : 5,000 VP  | +25% ATK & DEF
Rare    →  Mythic    : 10,000 VP | +25% ATK & DEF
Mythic  →  Legendary : 15,000 VP | +25% ATK & DEF
"""
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.queries import get_or_create_user, rarity_emoji
from db.client import get_db

ITEMS_PER_PAGE = 5

REFORGE_TABLE = {
    "Common": ("Rare",      5_000),
    "Rare":   ("Mythic",   10_000),
    "Mythic": ("Legendary",15_000),
}


def _get_forgeable_inventory(telegram_id: int) -> list[dict]:
    """Returns inventory items that can still be upgraded (not Legendary)."""
    db = get_db()
    res = (
        db.table("inventory")
        .select("id, caught_price, rarity, attack, defense, characters(name, anime)")
        .eq("telegram_id", telegram_id)
        .not_.eq("rarity", "Legendary")
        .order("caught_price", desc=True)
        .execute()
    )
    return res.data


def _list_keyboard(items: list[dict], page: int) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
    page_items  = items[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

    buttons = []
    for item in page_items:
        char        = item.get("characters") or {}
        name        = char.get("name", "?")
        rarity      = item.get("rarity", "Common")
        next_rarity, cost = REFORGE_TABLE[rarity]
        emoji       = rarity_emoji(rarity)
        next_emoji  = rarity_emoji(next_rarity)

        buttons.append([InlineKeyboardButton(
            f"{emoji} {name} → {next_emoji} {next_rarity} ({cost:,} VP)",
            callback_data=f"reforge_pick:{item['id']}:{page}",
        )])

    nav = []
    if total_pages > 1:
        nav.append(InlineKeyboardButton("⏮", callback_data="reforge_list:0"))
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"reforge_list:{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="reforge_noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"reforge_list:{page+1}"))
        nav.append(InlineKeyboardButton("⏭", callback_data=f"reforge_list:{total_pages-1}"))
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="reforge_cancel")])
    return InlineKeyboardMarkup(buttons)


def _confirm_keyboard(inv_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm Reforge", callback_data=f"reforge_confirm:{inv_id}:{page}"),
        InlineKeyboardButton("◀️ Back",            callback_data=f"reforge_list:{page}"),
    ]])


# ── Command ───────────────────────────────────────────────────────────────────

async def reforge_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.full_name, user.username)

    items = _get_forgeable_inventory(user.id)

    if not items:
        await update.message.reply_text(
            "⚒️ No characters available to reforge!\n\n"
            "Either your inventory is empty or all characters are already *Legendary* 🌟",
            parse_mode="Markdown",
        )
        return

    # Fetch current balance
    db      = get_db()
    res     = db.table("users").select("coins").eq("telegram_id", user.id).execute()
    balance = res.data[0]["coins"] if res.data else 0

    await update.message.reply_text(
        f"⚒️ *Reforge a Character*\n\n"
        f"💰 Your balance: *{balance:,} VP*\n\n"
        f"Choose a character to upgrade its rarity.\n"
        f"Stats are boosted by *+25%* on each reforge.",
        parse_mode="Markdown",
        reply_markup=_list_keyboard(items, 0),
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

async def reforge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user  = update.effective_user
    await query.answer()

    data = query.data

    if data == "reforge_noop":
        return

    if data == "reforge_cancel":
        await query.edit_message_text("❌ Reforge cancelled.")
        return

    # ── List page navigation ──────────────────────────────────────────────────
    if data.startswith("reforge_list:"):
        page  = int(data.split(":")[1])
        items = _get_forgeable_inventory(user.id)

        if not items:
            await query.edit_message_text("✅ No more characters to reforge.")
            return

        total_pages = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
        page        = max(0, min(page, total_pages - 1))

        db      = get_db()
        res     = db.table("users").select("coins").eq("telegram_id", user.id).execute()
        balance = res.data[0]["coins"] if res.data else 0

        await query.edit_message_text(
            f"⚒️ *Reforge a Character*\n\n"
            f"💰 Your balance: *{balance:,} VP*\n\n"
            f"Choose a character to upgrade its rarity.\n"
            f"Stats are boosted by *+25%* on each reforge.",
            parse_mode="Markdown",
            reply_markup=_list_keyboard(items, page),
        )
        return

    # ── Pick a character — show confirmation ──────────────────────────────────
    if data.startswith("reforge_pick:"):
        _, inv_id, page = data.split(":")
        inv_id = int(inv_id)
        page   = int(page)

        db  = get_db()
        res = (
            db.table("inventory")
            .select("id, rarity, attack, defense, characters(name, anime)")
            .eq("id", inv_id)
            .eq("telegram_id", user.id)
            .execute()
        )

        if not res.data:
            await query.edit_message_text("⚠️ Character not found in your inventory.")
            return

        item        = res.data[0]
        char        = item.get("characters") or {}
        name        = char.get("name", "?")
        anime       = char.get("anime", "?")
        rarity      = item["rarity"]
        attack      = item["attack"]
        defense     = item["defense"]
        next_rarity, cost = REFORGE_TABLE[rarity]

        new_atk = int(attack  * 1.25)
        new_def = int(defense * 1.25)

        bal_res = db.table("users").select("coins").eq("telegram_id", user.id).execute()
        balance = bal_res.data[0]["coins"] if bal_res.data else 0

        affordable = "✅" if balance >= cost else "❌ Insufficient VP"

        await query.edit_message_text(
            f"⚒️ *Reforge Confirmation*\n\n"
            f"🎴 *{name}* ({anime})\n\n"
            f"{rarity_emoji(rarity)} {rarity} → {rarity_emoji(next_rarity)} *{next_rarity}*\n\n"
            f"⚔️ Attack:  {attack} → *{new_atk}*\n"
            f"🛡 Defense: {defense} → *{new_def}*\n\n"
            f"💰 Cost: *{cost:,} VP* {affordable}\n"
            f"💳 Your balance: *{balance:,} VP*",
            parse_mode="Markdown",
            reply_markup=_confirm_keyboard(inv_id, page),
        )
        return

    # ── Confirm reforge ───────────────────────────────────────────────────────
    if data.startswith("reforge_confirm:"):
        _, inv_id, page = data.split(":")
        inv_id = int(inv_id)
        page   = int(page)

        db  = get_db()

        # Re-fetch item to prevent stale data
        res = (
            db.table("inventory")
            .select("id, rarity, attack, defense, characters(name)")
            .eq("id", inv_id)
            .eq("telegram_id", user.id)
            .execute()
        )

        if not res.data:
            await query.edit_message_text("⚠️ Character not found.")
            return

        item   = res.data[0]
        rarity = item["rarity"]

        if rarity not in REFORGE_TABLE:
            await query.edit_message_text("⚠️ This character can't be reforged further.")
            return

        next_rarity, cost = REFORGE_TABLE[rarity]
        name  = (item.get("characters") or {}).get("name", "?")

        # Check balance
        bal_res = db.table("users").select("coins").eq("telegram_id", user.id).execute()
        balance = bal_res.data[0]["coins"] if bal_res.data else 0

        if balance < cost:
            await query.edit_message_text(
                f"❌ Not enough VP!\n\n"
                f"You need *{cost:,} VP* but only have *{balance:,} VP*.",
                parse_mode="Markdown",
            )
            return

        # Compute new stats
        new_atk = int(item["attack"]  * 1.25)
        new_def = int(item["defense"] * 1.25)

        # Apply changes
        db.table("inventory").update({
            "rarity":  next_rarity,
            "attack":  new_atk,
            "defense": new_def,
        }).eq("id", inv_id).execute()

        db.rpc("increment_coins", {"user_id": user.id, "amount": -cost}).execute()

        new_balance = balance - cost

        # Show updated list
        items = _get_forgeable_inventory(user.id)
        total_pages = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
        page = max(0, min(page, total_pages - 1))

        reply_markup = _list_keyboard(items, page) if items else None
        footer = (
            f"\n\n⚒️ *Reforge another character?*\n"
            f"💰 Remaining balance: *{new_balance:,} VP*"
            if items else "\n\n✅ No more characters to reforge."
        )

        await query.edit_message_text(
            f"✅ *Reforge successful!*\n\n"
            f"🎴 *{name}* is now *{next_rarity}* {rarity_emoji(next_rarity)}\n\n"
            f"⚔️ Attack:  *{new_atk}*\n"
            f"🛡 Defense: *{new_def}*\n"
            f"💰 Spent: *{cost:,} VP*"
            + footer,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
        return