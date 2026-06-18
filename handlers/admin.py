"""
/admin — Bot owner panel (Telegram ID 1678605129 only).

Options:
  1. Manage Spawning  — paginated list of all groups the bot is in,
                        enable/disable spawning per group
  2. Edit Inventory   — pick a user → pick a character to edit rarity
                        OR add a character from the master list
"""

import math
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


# ─────────────────────────────────────────────────────────────────────────────
#  Keyboards
# ─────────────────────────────────────────────────────────────────────────────

def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Manage Spawning",   callback_data="adm_spawn_list:0")],
        [InlineKeyboardButton("🎒 Edit Inventory",    callback_data="adm_users_list:0")],
        [InlineKeyboardButton("❌ Close",              callback_data="adm_close")],
    ])


def _back_main() -> list:
    return [InlineKeyboardButton("◀️ Main menu", callback_data="adm_main")]


def _paged_keyboard(rows: list[list], page: int, total: int, prefix: str, back_cb: str) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(total / ITEMS_PER_PAGE))
    nav = []
    if total_pages > 1:
        nav.append(InlineKeyboardButton("⏮", callback_data=f"{prefix}:0"))
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"{prefix}:{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="adm_noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"{prefix}:{page+1}"))
        nav.append(InlineKeyboardButton("⏭", callback_data=f"{prefix}:{total_pages-1}"))

    buttons = rows[:]
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(buttons)


# ─────────────────────────────────────────────────────────────────────────────
#  Data helpers
# ─────────────────────────────────────────────────────────────────────────────

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
    res = db.table("characters").select("id, name, anime, base_price").order("name").execute()
    all_chars = res.data or []
    start = page * ITEMS_PER_PAGE
    return all_chars[start:start + ITEMS_PER_PAGE], len(all_chars)


# ─────────────────────────────────────────────────────────────────────────────
#  /admin command
# ─────────────────────────────────────────────────────────────────────────────

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _only_owner(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this.")
        return

    await update.message.reply_text(
        "🔧 *Admin Panel*\n\nChoose an option:",
        parse_mode="Markdown",
        reply_markup=_main_keyboard(),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Callback handler
# ─────────────────────────────────────────────────────────────────────────────

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user  = update.effective_user
    await query.answer()

    if not _only_owner(user.id):
        await query.answer("❌ Not authorised.", show_alert=True)
        return

    data = query.data

    # ── Close / noop ──────────────────────────────────────────────────────────
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

    # ─────────────────────────────────────────────────────────────────────────
    #  1. SPAWN MANAGEMENT
    # ─────────────────────────────────────────────────────────────────────────

    if data.startswith("adm_spawn_list:"):
        page        = int(data.split(":")[1])
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

        kb = _paged_keyboard(rows, page, total, "adm_spawn_list", "adm_main")
        await query.edit_message_text(
            "🌐 *Manage Spawning*\n\nSelect a group:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_spawn_group:"):
        _, gid, page = data.split(":")
        gid  = int(gid)
        page = int(page)

        db  = get_db()
        res = db.table("enabled_groups").select("group_name").eq("group_id", gid).execute()
        gname = res.data[0].get("group_name", f"Group {gid}") if res.data else f"Group {gid}"

        enabled = is_group_enabled(gid)
        status  = "✅ Enabled" if enabled else "❌ Disabled"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔴 Disable spawning" if enabled else "🟢 Enable spawning",
                callback_data=f"adm_spawn_toggle:{gid}:{page}",
            )],
            [InlineKeyboardButton("◀️ Back", callback_data=f"adm_spawn_list:{page}")],
        ])

        await query.edit_message_text(
            f"🌐 *{gname}*\n\nSpawning: {status}",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_spawn_toggle:"):
        _, gid, page = data.split(":")
        gid  = int(gid)
        page = int(page)

        db  = get_db()
        res = db.table("enabled_groups").select("group_name").eq("group_id", gid).execute()
        gname = res.data[0].get("group_name", f"Group {gid}") if res.data else f"Group {gid}"

        if is_group_enabled(gid):
            # Disable
            _cancel_spawn_job(context, gid)
            db.table("enabled_groups").delete().eq("group_id", gid).execute()
            status = "🔴 Spawning *disabled*"
        else:
            # Enable
            enable_group(gid, gname, OWNER_ID)
            context.job_queue.run_repeating(
                _auto_spawn,
                interval=SPAWN_INTERVAL,
                first=SPAWN_INTERVAL,
                data={"chat_id": gid},
                name=f"auto_spawn_{gid}",
            )
            status = "🟢 Spawning *enabled*"

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Back to group", callback_data=f"adm_spawn_group:{gid}:{page}"),
        ]])
        await query.edit_message_text(
            f"✅ *{gname}*\n\n{status}",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    # ─────────────────────────────────────────────────────────────────────────
    #  2. EDIT INVENTORY
    # ─────────────────────────────────────────────────────────────────────────

    if data.startswith("adm_users_list:"):
        page        = int(data.split(":")[1])
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
            uname = f"@{u['username']}" if u.get("username") else ""
            rows.append([InlineKeyboardButton(
                f"👤 {name} {uname}".strip(),
                callback_data=f"adm_user_menu:{uid}:{page}",
            )])

        kb = _paged_keyboard(rows, page, total, "adm_users_list", "adm_main")
        await query.edit_message_text(
            "👤 *Select a user:*",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_user_menu:"):
        _, uid, back_page = data.split(":")
        uid = int(uid)

        db  = get_db()
        res = db.table("users").select("full_name, username").eq("telegram_id", uid).execute()
        udata = res.data[0] if res.data else {}
        name  = udata.get("full_name") or udata.get("username") or str(uid)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Edit character",  callback_data=f"adm_edit_list:{uid}:0:{back_page}")],
            [InlineKeyboardButton("➕ Add character",    callback_data=f"adm_add_list:{uid}:0:{back_page}")],
            [InlineKeyboardButton("◀️ Back",             callback_data=f"adm_users_list:{back_page}")],
        ])
        await query.edit_message_text(
            f"🎒 *{name}'s inventory*\n\nWhat do you want to do?",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    # ── Edit character (change rarity) ────────────────────────────────────────

    if data.startswith("adm_edit_list:"):
        _, uid, page, back_page = data.split(":")
        uid  = int(uid)
        page = int(page)

        items, total = _get_user_inventory(uid, page)

        if not items:
            await query.edit_message_text(
                "🗂 This user has no characters.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Back", callback_data=f"adm_user_menu:{uid}:{back_page}"),
                ]]),
            )
            return

        rows = []
        for item in items:
            char   = item.get("characters") or {}
            name   = char.get("name", "?")
            rarity = item.get("rarity", "Common")
            emoji  = rarity_emoji(rarity)
            rows.append([InlineKeyboardButton(
                f"{emoji} {name} — {rarity}",
                callback_data=f"adm_edit_pick:{uid}:{item['id']}:{page}:{back_page}",
            )])

        kb = _paged_keyboard(rows, page, total, f"adm_edit_list:{uid}", f"adm_user_menu:{uid}:{back_page}")
        await query.edit_message_text(
            "✏️ *Select a character to edit:*",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_edit_pick:"):
        _, uid, inv_id, page, back_page = data.split(":")
        uid    = int(uid)
        inv_id = int(inv_id)
        page   = int(page)

        db  = get_db()
        res = db.table("inventory").select("rarity, characters(name)").eq("id", inv_id).execute()
        if not res.data:
            await query.edit_message_text("⚠️ Character not found.")
            return

        item   = res.data[0]
        name   = (item.get("characters") or {}).get("name", "?")
        rarity = item["rarity"]

        rarity_buttons = [
            InlineKeyboardButton(
                f"{'✅ ' if r == rarity else ''}{rarity_emoji(r)} {r}",
                callback_data=f"adm_edit_set:{uid}:{inv_id}:{r}:{page}:{back_page}",
            )
            for r in RARITIES
        ]

        kb = InlineKeyboardMarkup([
            rarity_buttons[:2],
            rarity_buttons[2:],
            [InlineKeyboardButton("◀️ Back", callback_data=f"adm_edit_list:{uid}:{page}:{back_page}")],
        ])
        await query.edit_message_text(
            f"✏️ *{name}*\nCurrent rarity: {rarity_emoji(rarity)} *{rarity}*\n\nSelect new rarity:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_edit_set:"):
        _, uid, inv_id, new_rarity, page, back_page = data.split(":")
        uid    = int(uid)
        inv_id = int(inv_id)
        page   = int(page)

        db  = get_db()
        res = db.table("inventory").select("characters(name)").eq("id", inv_id).execute()
        name = ((res.data[0].get("characters") or {}) if res.data else {}).get("name", "?")

        db.table("inventory").update({"rarity": new_rarity}).eq("id", inv_id).execute()

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Back to inventory", callback_data=f"adm_edit_list:{uid}:{page}:{back_page}"),
        ]])
        await query.edit_message_text(
            f"✅ *{name}* rarity changed to {rarity_emoji(new_rarity)} *{new_rarity}*",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    # ── Add character ─────────────────────────────────────────────────────────

    if data.startswith("adm_add_list:"):
        _, uid, page, back_page = data.split(":")
        uid  = int(uid)
        page = int(page)

        chars, total = _get_all_characters(page)

        rows = []
        for char in chars:
            rows.append([InlineKeyboardButton(
                f"{char['name']} ({char['anime']})",
                callback_data=f"adm_add_pick:{uid}:{char['id']}:{page}:{back_page}",
            )])

        kb = _paged_keyboard(rows, page, total, f"adm_add_list:{uid}", f"adm_user_menu:{uid}:{back_page}")
        await query.edit_message_text(
            "➕ *Select a character to add:*",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_add_pick:"):
        _, uid, char_id, page, back_page = data.split(":")
        uid     = int(uid)
        char_id = int(char_id)

        db  = get_db()
        res = db.table("characters").select("name, anime").eq("id", char_id).execute()
        if not res.data:
            await query.edit_message_text("⚠️ Character not found.")
            return

        char = res.data[0]

        rarity_buttons = [
            InlineKeyboardButton(
                f"{rarity_emoji(r)} {r}",
                callback_data=f"adm_add_confirm:{uid}:{char_id}:{r}:{page}:{back_page}",
            )
            for r in RARITIES
        ]

        kb = InlineKeyboardMarkup([
            rarity_buttons[:2],
            rarity_buttons[2:],
            [InlineKeyboardButton("◀️ Back", callback_data=f"adm_add_list:{uid}:{page}:{back_page}")],
        ])
        await query.edit_message_text(
            f"➕ *{char['name']}* ({char['anime']})\n\nSelect rarity to add with:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    if data.startswith("adm_add_confirm:"):
        _, uid, char_id, rarity, page, back_page = data.split(":")
        uid     = int(uid)
        char_id = int(char_id)

        db  = get_db()
        res = db.table("characters").select("*").eq("id", char_id).execute()
        if not res.data:
            await query.edit_message_text("⚠️ Character not found.")
            return

        char = res.data[0]

        import random
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

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Add another", callback_data=f"adm_add_list:{uid}:{page}:{back_page}"),
            InlineKeyboardButton("◀️ User menu",   callback_data=f"adm_user_menu:{uid}:{back_page}"),
        ]])

        await query.edit_message_text(
            f"✅ Added *{char['name']}* {rarity_emoji(rarity)} *{rarity}* to user's inventory!\n\n"
            f"⚔️ ATK: {attack} | 🛡 DEF: {defense} | 💰 {caught_price} VP",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return