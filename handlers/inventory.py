import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.queries import get_or_create_user, rarity_emoji, RARITY_ORDER
from db.client import get_db
from collections import defaultdict

ITEMS_PER_PAGE = 10

CLASS_EMOJI = {
    "Attacker":       "⚔️",
    "Defender":       "🛡",
    "Boost Attacker": "🔥",
    "Boost Defender": "💚",
}


def _get_inventory(telegram_id: int) -> list[dict]:
    db  = get_db()
    res = (
        db.table("inventory")
        .select("id, caught_price, rarity, attack, defense, characters(name, anime, class)")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return res.data or []


def _build_pages(items: list[dict]) -> list[list[dict]]:
    """
    Sort by rarity order then name, group into pages of ITEMS_PER_PAGE.
    Stacks duplicates (same character + rarity) into one entry.
    """
    # Stack duplicates: key = (name, anime, rarity)
    stacked: dict[tuple, dict] = {}
    for item in items:
        char   = item.get("characters") or {}
        name   = char.get("name", "?")
        anime  = char.get("anime",  "?")
        cls    = char.get("class",  "")
        rarity = item.get("rarity", "Common")
        key    = (name, anime, rarity, cls)

        if key not in stacked:
            stacked[key] = {
                "name":   name,
                "anime":  anime,
                "class":  cls,
                "rarity": rarity,
                "count":  0,
                "total_price": 0,
            }
        stacked[key]["count"]       += 1
        stacked[key]["total_price"] += item.get("caught_price", 0)

    # Sort by rarity order then name
    rarity_rank = {r: i for i, r in enumerate(RARITY_ORDER)}
    sorted_items = sorted(
        stacked.values(),
        key=lambda x: (rarity_rank.get(x["rarity"], 99), x["name"]),
    )

    # Split into pages
    pages = []
    for i in range(0, max(1, len(sorted_items)), ITEMS_PER_PAGE):
        pages.append(sorted_items[i:i + ITEMS_PER_PAGE])
    return pages


def _page_text(page_items: list[dict], page: int, total_pages: int, user_name: str, total_chars: int) -> str:
    lines = [f"🗂 *کالکشن {user_name}* — {total_chars} کارکتر\n"]

    current_rarity = None
    for item in page_items:
        rarity = item["rarity"]

        # Rarity section header
        if rarity != current_rarity:
            current_rarity = rarity
            emoji = rarity_emoji(rarity)
            lines.append(f"\n{emoji} *{rarity}*")

        name   = item["name"]
        anime  = item["anime"]
        cls    = item["class"]
        count  = item["count"]
        price  = item["total_price"]
        c_emoji = CLASS_EMOJI.get(cls, "")

        count_str = f"`{count}x` " if count > 1 else ""
        lines.append(
            f"{count_str}*{name}* {c_emoji}\n"
            f"  ┗ {anime} · 💰 {price:,} VP"
        )

    lines.append(f"\n📄 صفحه {page + 1} از {total_pages}")
    return "\n".join(lines)


def _nav_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None
    nav = []
    nav.append(InlineKeyboardButton("⏮", callback_data=f"inv_page:0"))
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"inv_page:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="inv_noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"inv_page:{page+1}"))
    nav.append(InlineKeyboardButton("⏭", callback_data=f"inv_page:{total_pages-1}"))
    return InlineKeyboardMarkup([nav])


async def inventory_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return

    get_or_create_user(user.id, user.full_name, user.username)
    items = _get_inventory(user.id)

    if not items:
        await update.message.reply_text(
            "🗂 اینونتوریت *خالیه*!\n\nبرو توی یک گروه فعال کارکترای مختلفو صید کن 🎴",
            parse_mode="Markdown",
        )
        return

    pages       = _build_pages(items)
    total_pages = len(pages)
    text        = _page_text(pages[0], 0, total_pages, user.first_name, len(items))
    kb          = _nav_keyboard(0, total_pages)

    # Store pages in context for callback reuse
    context.user_data[f"inv_{user.id}"] = pages

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user  = update.effective_user
    await query.answer()

    if query.data == "inv_noop":
        return

    page = int(query.data.split(":")[1])

    # Try cached pages first, rebuild if not cached
    cache_key = f"inv_{user.id}"
    pages     = context.user_data.get(cache_key)
    if not pages:
        items = _get_inventory(user.id)
        if not items:
            await query.edit_message_text("🗂 اینونتوریت خالیه!")
            return
        pages = _build_pages(items)
        context.user_data[cache_key] = pages

    total_pages = len(pages)
    page        = max(0, min(page, total_pages - 1))
    text        = _page_text(pages[page], page, total_pages, user.first_name, sum(i["count"] for p in pages for i in p))
    kb          = _nav_keyboard(page, total_pages)

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)