"""
/info — paginated character browser with detailed info cards.
"""
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.queries import get_or_create_user, rarity_emoji
from db.client import get_db

ITEMS_PER_PAGE = 5


def _get_full_inventory(telegram_id: int) -> list[dict]:
    db = get_db()
    res = (
        db.table("inventory")
        .select("id, caught_price, rarity, attack, defense, character_id, characters(name, anime, image_url, ability_name, ability_desc)")
        .eq("telegram_id", telegram_id)
        .order("caught_price", desc=True)
        .execute()
    )
    return res.data


def _list_keyboard(items: list[dict], page: int) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
    page_items  = items[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

    buttons = []
    for item in page_items:
        char   = item.get("characters") or {}
        name   = char.get("name", "?")
        rarity = item.get("rarity", "Common")
        emoji  = rarity_emoji(rarity)
        buttons.append([InlineKeyboardButton(
            f"{emoji} {name}",
            callback_data=f"info_view:{item['id']}:{page}",
        )])

    nav = []
    if total_pages > 1:
        nav.append(InlineKeyboardButton("⏮", callback_data=f"info_list:0"))
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"info_list:{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="info_noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"info_list:{page+1}"))
        nav.append(InlineKeyboardButton("⏭", callback_data=f"info_list:{total_pages-1}"))
        buttons.append(nav)

    return InlineKeyboardMarkup(buttons)


def _detail_keyboard(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Back to list", callback_data=f"info_list:{page}"),
    ]])


def _detail_text(item: dict) -> str:
    char         = item.get("characters") or {}
    name         = char.get("name", "?")
    anime        = char.get("anime", "?")
    rarity       = item.get("rarity", "Common")
    emoji        = rarity_emoji(rarity)
    attack       = item.get("attack", 0)
    defense      = item.get("defense", 0)
    price        = item.get("caught_price", 0)
    ability_name = char.get("ability_name", "") or "—"
    ability_desc = char.get("ability_desc", "") or "—"

    return (
        f"{emoji} *{name}*\n"
        f"🎌 Anime: *{anime}*\n"
        f"🏅 Rarity: *{rarity}*\n\n"
        f"⚔️ Attack:  *{attack}*\n"
        f"🛡 Defense: *{defense}*\n"
        f"💰 Value:   *{price:,} VP*\n\n"
        f"✨ *Ability — {ability_name}*\n"
        f"_{ability_desc}_"
    )


# ── Command ───────────────────────────────────────────────────────────────────

async def info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.full_name, user.username)

    items = _get_full_inventory(user.id)

    if not items:
        await update.message.reply_text(
            "🗂 Your inventory is empty — go catch some characters first!",
        )
        return

    keyboard = _list_keyboard(items, 0)
    await update.message.reply_text(
        f"📋 *Your characters* — tap one for details:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user  = update.effective_user
    await query.answer()

    data = query.data

    if data == "info_noop":
        return

    items = _get_full_inventory(user.id)

    # ── Back to list ──────────────────────────────────────────────────────────
    if data.startswith("info_list:"):
        page     = int(data.split(":")[1])
        page     = max(0, min(page, max(0, math.ceil(len(items) / ITEMS_PER_PAGE) - 1)))
        keyboard = _list_keyboard(items, page)

        await query.edit_message_text(
            "📋 *Your characters* — tap one for details:",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    # ── View character detail ─────────────────────────────────────────────────
    if data.startswith("info_view:"):
        _, inv_id, page = data.split(":")
        inv_id = int(inv_id)
        page   = int(page)

        item = next((i for i in items if i["id"] == inv_id), None)
        if not item:
            await query.edit_message_text("⚠️ Character not found.")
            return

        char      = item.get("characters") or {}
        image_url = char.get("image_url", "")
        text      = _detail_text(item)
        keyboard  = _detail_keyboard(page)

        if image_url:
            # Send new photo message and delete the list message
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=image_url,
                caption=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        else:
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        return