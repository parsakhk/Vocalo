"""
/admin — Bot owner panel (Telegram ID 1678605129 only).
"""

import math
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.client import get_db
from db.queries import rarity_emoji, is_group_enabled, enable_group
from handlers.enable import _cancel_spawn_job, _auto_spawn, SPAWN_INTERVAL

OWNER_ID       = 1678605129
ITEMS_PER_PAGE = 8
RARITIES       = ["Common", "Rare", "Mythic", "Legendary"]


def _only_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Manage Spawning", callback_data="adm_spawn_list:0")],
        [InlineKeyboardButton("🎒 Edit Inventory",  callback_data="adm_users_list:0")],
        [InlineKeyboardButton("❌ Close",            callback_data="adm_close")],
    ])


def _nav_row(page: int, total_pages: int, page_cb: str) -> list:
    """
    page_cb must be a format string with ONE {} for the page number.
    e.g. "adm_edit_list:123:{}:0"
    """
    if total_pages <= 1:
        return []
    nav = []
    nav.append(InlineKeyboardButton("⏮", callback_data=page_cb.format(0)))
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=page_cb.format(page - 1)))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="adm_noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=page_cb.format(page + 1)))
    nav.append(InlineKeyboardButton("⏭", callback_data=page_cb.format(total_pages - 1)))
    return nav


def _build_kb(rows: list, page: int, total: int, page_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(total / ITEMS_PER_PAGE))
    buttons     = rows[:]
    nav         = _nav_row(page, total_pages, page_cb)
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(buttons)


# ── Data helpers ──────────────────────────────────────────────────────────────

def _get_groups(page: int) -> tuple[list, int]:
    db  = get_db()
    res = db.table("enabled_groups").select("group_id, group_name").execute()
    all_groups = res.data or []
    start = page * ITEMS_PER_PAGE
    return all_groups[start:start + ITEMS_PER_PAGE], len(all_groups)


def _get_users(page: int) -> tuple[list, int]:
    db  = get_db()
    res = db.table("users").select("telegram_id, full_name, username").order("full_name").execute()
    all_users = res.data or []
    start = page * ITEMS_PER_PAGE
    return all_users[start:start + ITEMS_PER_PAGE], len(all_users)


def _get_user_inventory(telegram_id: int, page: int) -> tuple[list, int]:
    db  = get_db()
    res = (
        db.table("inventory")
        .select("id, rarity, characters(name, anime)")
        .eq("telegram_id", telegram_id)
        .order("caught_price", desc=True)
        .execute()
    )
    all_items = res.data or []
    start = page * ITEMS_PER_PAGE
    return all_items[start:start + ITEMS_PER_PAGE], len(all_items)


def _get_all_characters(page: int) -> tuple[list, int]:
    db  = get_db()
    res = db.table("characters").select("id, name, anime, base_price, atk_min, atk_max, def_min, def_max").order("name").execute()
    all_chars = res.data or []
    start = page * ITEMS_PER_PAGE
    return all_chars[start:start + ITEMS_PER_PAGE], len(all_chars)


# ── /admin command ────────────────────────────────────────────────────────────

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _only_owner(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this.")
        return
    await update.message.reply_text(
        "🔧 *Admin Panel*\n\nChoose an option:",
        parse_mode="Markdown",
        reply_markup=_main_keyboard(),
    )


# ── Callback handler ──────────────────────────────────────────────────────────

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user  = update.effective_user
    await query.answer()

    if not _only_owner(user.id):
        await query.answer("❌ Not authorised.", show_alert=True)
        return

    data = query.data

    if data == "adm_close":
        await query.message.delete()
        return

    if data == "adm_noop":
        return

    if data == "adm_main":
        await query.edit_message_text(
            "🔧 *Admin Panel*\n\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=_main_keyboard(),
        )
        return

    # ── Spawn management ──────────────────────────────────────────────────────

    if data.startswith("adm_spawn_list:"):
        page          = int(data.split(":")[1])
        groups, total = _get_groups(page)

        if not groups:
            await query.edit_message_text(
                "🌐 No enabled groups found yet.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="adm_main")]]),
            )
            return

        rows = []
        for g in groups:
            gid   = g["group_id"]
            gname = g.get("group_name") or f"Group {gid}"
            rows.append([InlineKeyboardButton(
                f"🌐 {gname}",
                callback_data=f"adm_spawn_group:{gid}:{page}",
            )])

        kb = _build_kb(rows, page, total, "adm_spawn_list:{}", "adm_main")
        await query.edit_message_text(
            "🌐 *Manage Spawning*\n\nSelect a group:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_spawn_group:"):
        parts = data.split(":")
        gid, back_page = int(parts[1]), parts[2]
        db    = get_db()
        res   = db.table("enabled_groups").select("group_name").eq("group_id", gid).execute()
        gname = res.data[0].get("group_name", f"Group {gid}") if res.data else f"Group {gid}"
        enabled = is_group_enabled(gid)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔴 Disable spawning" if enabled else "🟢 Enable spawning",
                callback_data=f"adm_spawn_toggle:{gid}:{back_page}",
            )],
            [InlineKeyboardButton("◀️ Back", callback_data=f"adm_spawn_list:{back_page}")],
        ])
        await query.edit_message_text(
            f"🌐 *{gname}*\n\nSpawning: {'✅ Enabled' if enabled else '❌ Disabled'}",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_spawn_toggle:"):
        parts = data.split(":")
        gid, back_page = int(parts[1]), parts[2]
        db    = get_db()
        res   = db.table("enabled_groups").select("group_name").eq("group_id", gid).execute()
        gname = res.data[0].get("group_name", f"Group {gid}") if res.data else f"Group {gid}"

        if is_group_enabled(gid):
            _cancel_spawn_job(context, gid)
            db.table("enabled_groups").delete().eq("group_id", gid).execute()
            msg = "🔴 Spawning *disabled*"
        else:
            enable_group(gid, gname, OWNER_ID)
            context.job_queue.run_repeating(
                _auto_spawn, interval=SPAWN_INTERVAL, first=SPAWN_INTERVAL,
                data={"chat_id": gid}, name=f"auto_spawn_{gid}",
            )
            msg = "🟢 Spawning *enabled*"

        await query.edit_message_text(
            f"✅ *{gname}*\n\n{msg}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Back", callback_data=f"adm_spawn_group:{gid}:{back_page}"),
            ]]),
        )
        return

    # ── User list ─────────────────────────────────────────────────────────────

    if data.startswith("adm_users_list:"):
        page         = int(data.split(":")[1])
        users, total = _get_users(page)

        if not users:
            await query.edit_message_text(
                "👤 No users found.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="adm_main")]]),
            )
            return

        rows = []
        for u in users:
            uid   = u["telegram_id"]
            name  = u.get("full_name") or u.get("username") or str(uid)
            uname = f" @{u['username']}" if u.get("username") else ""
            rows.append([InlineKeyboardButton(
                f"👤 {name}{uname}",
                callback_data=f"adm_user_menu:{uid}:{page}",
            )])

        kb = _build_kb(rows, page, total, "adm_users_list:{}", "adm_main")
        await query.edit_message_text(
            "👤 *Select a user:*",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_user_menu:"):
        parts = data.split(":")
        uid, back_page = int(parts[1]), parts[2]
        db  = get_db()
        res = db.table("users").select("full_name, username").eq("telegram_id", uid).execute()
        u   = res.data[0] if res.data else {}
        name = u.get("full_name") or u.get("username") or str(uid)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Edit character", callback_data=f"adm_edit_list:{uid}:0:{back_page}")],
            [InlineKeyboardButton("➕ Add character",  callback_data=f"adm_add_list:{uid}:0:{back_page}")],
            [InlineKeyboardButton("◀️ Back",           callback_data=f"adm_users_list:{back_page}")],
        ])
        await query.edit_message_text(
            f"🎒 *{name}'s inventory*\n\nWhat do you want to do?",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    # ── Edit character ────────────────────────────────────────────────────────

    if data.startswith("adm_edit_list:"):
        parts = data.split(":")
        uid, page, back_page = int(parts[1]), int(parts[2]), parts[3]
        items, total = _get_user_inventory(uid, page)

        if not items:
            await query.edit_message_text(
                "🗂 This user has no characters.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Back", callback_data=f"adm_user_menu:{uid}:{back_page}"),
                ]]),
            )
            return

        rows = [[InlineKeyboardButton(
            f"{rarity_emoji(i.get('rarity','Common'))} {(i.get('characters') or {}).get('name','?')} — {i.get('rarity','Common')}",
            callback_data=f"adm_edit_pick:{uid}:{i['id']}:{page}:{back_page}",
        )] for i in items]

        kb = _build_kb(rows, page, total, f"adm_edit_list:{uid}:{{}}:{back_page}", f"adm_user_menu:{uid}:{back_page}")
        await query.edit_message_text(
            "✏️ *Select a character to edit:*",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_edit_pick:"):
        parts = data.split(":")
        uid, inv_id, page, back_page = int(parts[1]), int(parts[2]), parts[3], parts[4]
        db  = get_db()
        res = db.table("inventory").select("rarity, characters(name)").eq("id", inv_id).execute()
        if not res.data:
            await query.edit_message_text("⚠️ Character not found.")
            return
        item   = res.data[0]
        name   = (item.get("characters") or {}).get("name", "?")
        rarity = item["rarity"]

        rarity_btns = [
            InlineKeyboardButton(
                f"{'✅ ' if r == rarity else ''}{rarity_emoji(r)} {r}",
                callback_data=f"adm_edit_set:{uid}:{inv_id}:{r}:{page}:{back_page}",
            )
            for r in RARITIES
        ]
        kb = InlineKeyboardMarkup([
            rarity_btns[:2], rarity_btns[2:],
            [InlineKeyboardButton("◀️ Back", callback_data=f"adm_edit_list:{uid}:{page}:{back_page}")],
        ])
        await query.edit_message_text(
            f"✏️ *{name}*\nCurrent: {rarity_emoji(rarity)} *{rarity}*\n\nSelect new rarity:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_edit_set:"):
        parts = data.split(":")
        uid, inv_id, new_rarity, page, back_page = int(parts[1]), int(parts[2]), parts[3], parts[4], parts[5]
        db  = get_db()
        res = db.table("inventory").select("characters(name)").eq("id", inv_id).execute()
        name = ((res.data[0].get("characters") or {}) if res.data else {}).get("name", "?")
        db.table("inventory").update({"rarity": new_rarity}).eq("id", inv_id).execute()

        await query.edit_message_text(
            f"✅ *{name}* → {rarity_emoji(new_rarity)} *{new_rarity}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Back to inventory", callback_data=f"adm_edit_list:{uid}:{page}:{back_page}"),
            ]]),
        )
        return

    # ── Add character ─────────────────────────────────────────────────────────

    if data.startswith("adm_add_list:"):
        parts = data.split(":")
        uid, page, back_page = int(parts[1]), int(parts[2]), parts[3]
        chars, total = _get_all_characters(page)

        rows = [[InlineKeyboardButton(
            f"{c['name']} ({c['anime']})",
            callback_data=f"adm_add_pick:{uid}:{c['id']}:{page}:{back_page}",
        )] for c in chars]

        kb = _build_kb(rows, page, total, f"adm_add_list:{uid}:{{}}:{back_page}", f"adm_user_menu:{uid}:{back_page}")
        await query.edit_message_text(
            "➕ *Select a character to add:*",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_add_pick:"):
        parts = data.split(":")
        uid, char_id, page, back_page = int(parts[1]), int(parts[2]), parts[3], parts[4]
        db  = get_db()
        res = db.table("characters").select("name, anime").eq("id", char_id).execute()
        if not res.data:
            await query.edit_message_text("⚠️ Character not found.")
            return
        char = res.data[0]

        rarity_btns = [
            InlineKeyboardButton(
                f"{rarity_emoji(r)} {r}",
                callback_data=f"adm_add_confirm:{uid}:{char_id}:{r}:{page}:{back_page}",
            )
            for r in RARITIES
        ]
        kb = InlineKeyboardMarkup([
            rarity_btns[:2], rarity_btns[2:],
            [InlineKeyboardButton("◀️ Back", callback_data=f"adm_add_list:{uid}:{page}:{back_page}")],
        ])
        await query.edit_message_text(
            f"➕ *{char['name']}* ({char['anime']})\n\nSelect rarity:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_add_confirm:"):
        parts = data.split(":")
        uid, char_id, rarity, page, back_page = int(parts[1]), int(parts[2]), parts[3], parts[4], parts[5]
        db  = get_db()
        res = db.table("characters").select("*").eq("id", char_id).execute()
        if not res.data:
            await query.edit_message_text("⚠️ Character not found.")
            return
        char         = res.data[0]
        multiplier   = round(random.uniform(1.0, 1.5), 2)
        caught_price = int(char["base_price"] * multiplier)
        attack       = random.randint(char.get("atk_min", 50), char.get("atk_max", 150))
        defense      = random.randint(char.get("def_min", 30), char.get("def_max", 100))

        db.table("inventory").insert({
            "telegram_id":  uid,
            "character_id": char_id,
            "caught_price": caught_price,
            "rarity":       rarity,
            "attack":       attack,
            "defense":      defense,
        }).execute()

        await query.edit_message_text(
            f"✅ Added *{char['name']}* {rarity_emoji(rarity)} *{rarity}*!\n\n"
            f"⚔️ ATK: {attack} | 🛡 DEF: {defense} | 💰 {caught_price} VP",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Add another", callback_data=f"adm_add_list:{uid}:{page}:{back_page}"),
                InlineKeyboardButton("◀️ User menu",  callback_data=f"adm_user_menu:{uid}:{back_page}"),
            ]]),
        )
        return