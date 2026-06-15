from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from db.queries import get_inventory, get_or_create_user
from db.client import get_db
import math

ITEMS_PER_PAGE = 5


def _sell_price(caught_price: int) -> int:
    return int(caught_price * 0.75)


def _build_keyboard(items: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    start = page * ITEMS_PER_PAGE
    page_items = items[start:start + ITEMS_PER_PAGE]

    buttons = []
    for item in page_items:
        char       = item.get("characters") or {}
        name       = char.get("name", "Unknown")
        sell_price = _sell_price(item["caught_price"])
        inv_id     = item["id"]
        buttons.append([
            InlineKeyboardButton(
                f"{name} — {sell_price} VP",
                callback_data=f"sell_item:{inv_id}:{page}"
            )
        ])

    # Navigation row
    nav = []
    if total_pages > 1:
        nav.append(InlineKeyboardButton("⏮", callback_data=f"sell_page:0"))
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"sell_page:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="sell_noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"sell_page:{page + 1}"))
        nav.append(InlineKeyboardButton("⏭", callback_data=f"sell_page:{total_pages - 1}"))
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="sell_cancel")])
    return InlineKeyboardMarkup(buttons)


async def sell_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.full_name, user.username)

    items = _get_full_inventory(user.id)

    if not items:
        await update.message.reply_text(
            "🗂 Your inventory is empty — nothing to sell!",
        )
        return

    total_pages = math.ceil(len(items) / ITEMS_PER_PAGE)
    keyboard    = _build_keyboard(items, 0, total_pages)

    await update.message.reply_text(
        "💰 *Which character do you want to sell?*\n\n"
        "_Each character sells for 75% of its value in Vocalo Points._",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user  = update.effective_user
    await query.answer()

    data = query.data

    # ── No-op (page indicator button) ────────────────────────────────────────
    if data == "sell_noop":
        return

    # ── Cancel ────────────────────────────────────────────────────────────────
    if data == "sell_cancel":
        await query.edit_message_text("❌ Sell cancelled.")
        return

    items       = _get_full_inventory(user.id)
    total_pages = math.ceil(len(items) / ITEMS_PER_PAGE)

    # ── Page navigation ───────────────────────────────────────────────────────
    if data.startswith("sell_page:"):
        page     = int(data.split(":")[1])
        keyboard = _build_keyboard(items, page, total_pages)
        await query.edit_message_reply_markup(reply_markup=keyboard)
        return

    # ── Sell item ─────────────────────────────────────────────────────────────
    if data.startswith("sell_item:"):
        _, inv_id, page_str = data.split(":")
        inv_id = int(inv_id)
        page   = int(page_str)

        db = get_db()

        # Verify item belongs to this user
        item_res = (
            db.table("inventory")
            .select("*, characters(name, anime)")
            .eq("id", inv_id)
            .eq("telegram_id", user.id)
            .execute()
        )

        if not item_res.data:
            await query.edit_message_text("⚠️ Character not found in your inventory.")
            return

        item       = item_res.data[0]
        char       = item.get("characters") or {}
        name       = char.get("name", "Unknown")
        anime      = char.get("anime", "?")
        sell_price = _sell_price(item["caught_price"])

        # Delete from inventory
        db.table("inventory").delete().eq("id", inv_id).execute()

        # Add Vocalo Points to user
        db.rpc("increment_coins", {
            "user_id": user.id,
            "amount":  sell_price,
        }).execute()

        # Refresh items and show updated list or done message
        items = _get_full_inventory(user.id)

        if not items:
            await query.edit_message_text(
                f"✅ Sold *{name}* ({anime}) for *{sell_price} Vocalo Points*!\n\n"
                f"Your inventory is now empty.",
                parse_mode="Markdown",
            )
            return

        total_pages = math.ceil(len(items) / ITEMS_PER_PAGE)
        page        = min(page, total_pages - 1)  # stay on same page if possible
        keyboard    = _build_keyboard(items, page, total_pages)

        await query.edit_message_text(
            f"✅ Sold *{name}* ({anime}) for *{sell_price} Vocalo Points*!\n\n"
            f"💰 *Which character do you want to sell next?*\n"
            f"_Each character sells for 75% of its value._",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


def _get_full_inventory(telegram_id: int) -> list[dict]:
    """Fetches inventory with id included for sell operations."""
    db = get_db()
    res = (
        db.table("inventory")
        .select("id, caught_price, rarity, characters(name, anime)")
        .eq("telegram_id", telegram_id)
        .order("caught_price", desc=True)
        .execute()
    )
    return res.data