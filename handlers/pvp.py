

import math
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.queries import get_or_create_user, rarity_emoji
from db.client import get_db

TEAM_SIZE      = 4
ITEMS_PER_PAGE = 5
CLASS_EMOJI    = {
    "Attacker":       "⚔️",
    "Defender":       "🛡",
    "Boost Attacker": "🔥",
    "Boost Defender": "💚",
}

# In-memory PVP sessions { pvp_id: PVPState }
_pvp: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pvp_id(a: int, b: int) -> str:
    return f"pvp_{min(a,b)}_{max(a,b)}"


def _get_inventory(telegram_id: int) -> list[dict]:
    db = get_db()
    res = (
        db.table("inventory")
        .select("id, attack, defense, rarity, characters(name, anime, class)")
        .eq("telegram_id", telegram_id)
        .order("caught_price", desc=True)
        .execute()
    )
    return res.data


def _team_hp(team: list[dict]) -> int:
    return sum(i["defense"] for i in team)


def _team_atk(team: list[dict]) -> int:
    return sum(i["attack"] for i in team)


def _validate_team(selected: list[dict]) -> str | None:
    """Returns error string or None if valid."""
    if len(selected) != TEAM_SIZE:
        return f"You must pick exactly {TEAM_SIZE} characters."
    classes = {(i.get("characters") or {}).get("class", "") for i in selected}
    if "Attacker" not in classes and "Boost Attacker" not in classes:
        return "Your team needs at least one Attacker or Boost Attacker."
    if "Defender" not in classes and "Boost Defender" not in classes:
        return "Your team needs at least one Defender or Boost Defender."
    return None


def _pick_keyboard(items: list[dict], selected_ids: set, page: int, pid: str, role: str) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
    page_items  = items[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

    buttons = []
    for item in page_items:
        char    = item.get("characters") or {}
        name    = char.get("name", "?")
        cls     = char.get("class", "?")
        rarity  = item.get("rarity", "Common")
        inv_id  = item["id"]
        check   = "✅ " if inv_id in selected_ids else ""
        c_emoji = CLASS_EMOJI.get(cls, "❓")
        r_emoji = rarity_emoji(rarity)
        buttons.append([InlineKeyboardButton(
            f"{check}{r_emoji} {name} {c_emoji}",
            callback_data=f"{pid}_{role}_toggle:{inv_id}:{page}",
        )])

    nav = []
    if total_pages > 1:
        nav.append(InlineKeyboardButton("⏮", callback_data=f"{pid}_{role}_page:0"))
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"{pid}_{role}_page:{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data=f"{pid}_{role}_noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"{pid}_{role}_page:{page+1}"))
        nav.append(InlineKeyboardButton("⏭", callback_data=f"{pid}_{role}_page:{total_pages-1}"))
        buttons.append(nav)

    count = len(selected_ids)
    buttons.append([
        InlineKeyboardButton(
            f"✅ Confirm team ({count}/{TEAM_SIZE})",
            callback_data=f"{pid}_{role}_confirm",
        ),
        InlineKeyboardButton("❌ Cancel", callback_data=f"{pid}_{role}_cancel"),
    ])
    return InlineKeyboardMarkup(buttons)


def _team_summary(team: list[dict], label: str) -> str:
    lines = [f"*{label}* (HP: {_team_hp(team)})\n"]
    for item in team:
        char    = item.get("characters") or {}
        name    = char.get("name", "?")
        cls     = char.get("class", "?")
        c_emoji = CLASS_EMOJI.get(cls, "❓")
        r_emoji = rarity_emoji(item.get("rarity", "Common"))
        lines.append(f"  {r_emoji} {name} {c_emoji} | ⚔️{item['attack']} 🛡{item['defense']}")
    return "\n".join(lines)


def _battle_status(state: dict) -> str:
    c_hp  = state["challenger_hp"]
    o_hp  = state["opponent_hp"]
    c_name = state["challenger_name"]
    o_name = state["opponent_name"]
    rd     = state["round"]

    return (
        f"⚔️ *PVP Battle — Round {rd}*\n\n"
        f"🔴 {c_name}: *{c_hp} HP*\n"
        f"🔵 {o_name}: *{o_hp} HP*\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Battle engine
# ─────────────────────────────────────────────────────────────────────────────

def _do_round(state: dict) -> str:
    """Executes one round and returns the round log text."""
    c_team   = state["challenger_team"]
    o_team   = state["opponent_team"]
    c_name   = state["challenger_name"]
    o_name   = state["opponent_name"]
    c_atk_boost = state.get("challenger_atk_boost", 1.0)
    o_atk_boost = state.get("opponent_atk_boost", 1.0)
    c_def_boost = state.get("challenger_def_boost", 1.0)
    o_def_boost = state.get("opponent_def_boost", 1.0)

    # Reset boosts for this round
    state["challenger_atk_boost"] = 1.0
    state["opponent_atk_boost"]   = 1.0
    state["challenger_def_boost"] = 1.0
    state["opponent_def_boost"]   = 1.0

    # Pick one random fighter from each side
    c_fighter = random.choice(c_team)
    o_fighter = random.choice(o_team)
    c_char    = c_fighter.get("characters") or {}
    o_char    = o_fighter.get("characters") or {}
    c_cls     = c_char.get("class", "Attacker")
    o_cls     = o_char.get("class", "Attacker")
    c_fname   = c_char.get("name", "?")
    o_fname   = o_char.get("name", "?")

    log = [
        f"⚡ *{c_fname}* ({c_cls}) vs *{o_fname}* ({o_cls})\n"
    ]

    # ── Challenger's action ───────────────────────────────────────────────────
    if c_cls == "Attacker":
        dmg = int(c_fighter["attack"] * c_atk_boost)
        state["opponent_hp"] -= dmg
        log.append(f"⚔️ {c_fname} attacks for *{dmg} DMG*!")

    elif c_cls == "Defender":
        heal = int(50 * c_def_boost)
        state["challenger_hp"] += heal
        log.append(f"🛡 {c_fname} defends! *+{heal} HP* for {c_name}!")

    elif c_cls == "Boost Attacker":
        state["challenger_atk_boost"] = 1.5
        log.append(f"🔥 {c_fname} boosts {c_name}'s team ATK by *×1.5* next round!")

    elif c_cls == "Boost Defender":
        bonus = int(sum(i["defense"] for i in c_team) * 0.5)
        state["challenger_hp"] += bonus
        state["challenger_def_boost"] = 1.5
        log.append(f"💚 {c_fname} boosts {c_name}'s team DEF! *+{bonus} HP*!")

    # ── Opponent's action ─────────────────────────────────────────────────────
    if o_cls == "Attacker":
        dmg = int(o_fighter["attack"] * o_atk_boost)
        state["challenger_hp"] -= dmg
        log.append(f"⚔️ {o_fname} attacks for *{dmg} DMG*!")

    elif o_cls == "Defender":
        heal = int(50 * o_def_boost)
        state["opponent_hp"] += heal
        log.append(f"🛡 {o_fname} defends! *+{heal} HP* for {o_name}!")

    elif o_cls == "Boost Attacker":
        state["opponent_atk_boost"] = 1.5
        log.append(f"🔥 {o_fname} boosts {o_name}'s team ATK by *×1.5* next round!")

    elif o_cls == "Boost Defender":
        bonus = int(sum(i["defense"] for i in o_team) * 0.5)
        state["opponent_hp"] += bonus
        state["opponent_def_boost"] = 1.5
        log.append(f"💚 {o_fname} boosts {o_name}'s team DEF! *+{bonus} HP*!")

    state["round"] += 1
    return "\n".join(log)


async def _finish_battle(context, chat_id: int, state: dict, pid: str) -> None:
    """Determines winner, transfers characters, sends result."""
    c_hp   = state["challenger_hp"]
    o_hp   = state["opponent_hp"]
    c_id   = state["challenger_id"]
    o_id   = state["opponent_id"]
    c_name = state["challenger_name"]
    o_name = state["opponent_name"]

    if c_hp <= 0 and o_hp <= 0:
        winner_id, loser_id = (c_id, o_id) if c_hp > o_hp else (o_id, c_id)
    elif c_hp <= 0:
        winner_id, loser_id = o_id, c_id
    else:
        winner_id, loser_id = c_id, o_id

    winner_name = c_name if winner_id == c_id else o_name
    loser_name  = o_name if winner_id == c_id else c_name
    loser_team  = state["opponent_team"] if winner_id == c_id else state["challenger_team"]

    # Transfer loser's team to winner
    db = get_db()
    for item in loser_team:
        db.table("inventory").update({"telegram_id": winner_id}).eq("id", item["id"]).execute()

    chars_won = ", ".join((i.get("characters") or {}).get("name", "?") for i in loser_team)

    del _pvp[pid]

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🏆 *Battle Over!*\n\n"
            f"🥇 *{winner_name}* wins!\n"
            f"💀 *{loser_name}* has been defeated!\n\n"
            f"📦 *{winner_name}* claimed: {chars_won}"
        ),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  /pvp command
# ─────────────────────────────────────────────────────────────────────────────

async def pvp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    challenger = update.effective_user
    get_or_create_user(challenger.id, challenger.full_name, challenger.username)

    if not context.args:
        await update.message.reply_text("Usage: `/pvp @username`", parse_mode="Markdown")
        return

    raw = context.args[0].lstrip("@")
    db  = get_db()
    res = db.table("users").select("*").eq("username", raw).execute()

    if not res.data:
        await update.message.reply_text(f"⚠️ @{raw} not found. They need to /signin first.")
        return

    opponent = res.data[0]

    if opponent["telegram_id"] == challenger.id:
        await update.message.reply_text("⚠️ You can't battle yourself.")
        return

    pid = _pvp_id(challenger.id, opponent["telegram_id"])
    if pid in _pvp:
        await update.message.reply_text("⚠️ A battle between you two is already active!")
        return

    items = _get_inventory(challenger.id)
    if len(items) < TEAM_SIZE:
        await update.message.reply_text(f"❌ You need at least {TEAM_SIZE} characters to battle!")
        return

    _pvp[pid] = {
        "challenger_id":    challenger.id,
        "challenger_name":  challenger.first_name,
        "opponent_id":      opponent["telegram_id"],
        "opponent_name":    opponent.get("full_name", raw),
        "challenger_team":  [],
        "opponent_team":    [],
        "challenger_sel":   set(),
        "opponent_sel":     set(),
        "phase":            "challenger_pick",
        "challenger_hp":    0,
        "opponent_hp":      0,
        "challenger_atk_boost": 1.0,
        "opponent_atk_boost":   1.0,
        "challenger_def_boost": 1.0,
        "opponent_def_boost":   1.0,
        "round":            1,
        "chat_id":          update.effective_chat.id,
    }

    kb = _pick_keyboard(items, set(), 0, pid, "c")
    await update.message.reply_text(
        f"⚔️ *PVP Challenge!*\n\n"
        f"*{challenger.first_name}* vs *{opponent.get('full_name', raw)}*\n\n"
        f"🧑 *{challenger.first_name}*, pick your {TEAM_SIZE} characters!\n"
        f"_(Need at least 1 Attacker/Boost Attacker + 1 Defender/Boost Defender)_",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Callback router
# ─────────────────────────────────────────────────────────────────────────────

async def pvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user  = update.effective_user
    await query.answer()

    data = query.data

    # Find matching pvp session
    pid   = None
    state = None
    for key in _pvp:
        if data.startswith(key):
            pid   = key
            state = _pvp[key]
            break

    if not state:
        await query.edit_message_text("⚠️ This PVP session has expired.")
        return

    # Determine role from callback prefix
    rest = data[len(pid)+1:]   # e.g. "c_toggle:123:0" or "o_confirm"
    role = rest[0]             # "c" or "o"
    action = rest[2:]          # "toggle:123:0" etc

    # Access control
    is_challenger = (user.id == state["challenger_id"])
    is_opponent   = (user.id == state["opponent_id"])

    if role == "c" and not is_challenger:
        await query.answer("It's not your turn!", show_alert=True)
        return
    if role == "o" and not is_opponent:
        await query.answer("It's not your turn!", show_alert=True)
        return

    sel_key   = "challenger_sel"   if role == "c" else "opponent_sel"
    owner_id  = state["challenger_id"] if role == "c" else state["opponent_id"]
    owner_name = state["challenger_name"] if role == "c" else state["opponent_name"]

    parts = action.split(":")

    if parts[0] == "noop":
        return

    if parts[0] == "cancel":
        del _pvp[pid]
        await query.edit_message_text("❌ PVP challenge cancelled.")
        return

    if parts[0] == "page":
        page  = int(parts[1])
        items = _get_inventory(owner_id)
        kb    = _pick_keyboard(items, state[sel_key], page, pid, role)
        await query.edit_message_reply_markup(reply_markup=kb)
        return

    if parts[0] == "toggle":
        inv_id = int(parts[1])
        page   = int(parts[2])
        sel    = state[sel_key]

        if inv_id in sel:
            sel.discard(inv_id)
        else:
            if len(sel) >= TEAM_SIZE:
                await query.answer(f"Max {TEAM_SIZE} characters!", show_alert=True)
                return
            sel.add(inv_id)

        items = _get_inventory(owner_id)
        kb    = _pick_keyboard(items, sel, page, pid, role)
        await query.edit_message_reply_markup(reply_markup=kb)
        return

    if parts[0] == "confirm":
        items    = _get_inventory(owner_id)
        selected = [i for i in items if i["id"] in state[sel_key]]
        err      = _validate_team(selected)

        if err:
            await query.answer(err, show_alert=True)
            return

        team_key = "challenger_team" if role == "c" else "opponent_team"
        hp_key   = "challenger_hp"   if role == "c" else "opponent_hp"
        state[team_key] = selected
        state[hp_key]   = _team_hp(selected)

        if role == "c":
            # Challenger confirmed — now opponent picks
            state["phase"] = "opponent_pick"
            opp_items      = _get_inventory(state["opponent_id"])

            if len(opp_items) < TEAM_SIZE:
                del _pvp[pid]
                await query.edit_message_text(
                    f"❌ {state['opponent_name']} doesn't have enough characters to battle!"
                )
                return

            summary = _team_summary(selected, f"{state['challenger_name']}'s Team")
            kb      = _pick_keyboard(opp_items, set(), 0, pid, "o")

            await query.edit_message_text(
                f"⚔️ *PVP Battle*\n\n"
                f"{summary}\n\n"
                f"🧑 *{state['opponent_name']}*, now pick YOUR {TEAM_SIZE} characters!",
                parse_mode="Markdown",
                reply_markup=kb,
            )

        else:
            # Both teams confirmed — start battle
            state["phase"] = "battle"
            c_summary = _team_summary(state["challenger_team"], f"🔴 {state['challenger_name']}")
            o_summary = _team_summary(selected, f"🔵 {state['opponent_name']}")

            await query.edit_message_text(
                f"⚔️ *Battle Begins!*\n\n"
                f"{c_summary}\n\n"
                f"{o_summary}\n\n"
                f"Press the button to start Round 1!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚔️ Fight!", callback_data=f"{pid}_fight"),
                ]]),
            )
        return

    # ── Fight round ───────────────────────────────────────────────────────────
    if action == "fight":
        if user.id not in (state["challenger_id"], state["opponent_id"]):
            await query.answer("You're not in this battle!", show_alert=True)
            return

        round_log = _do_round(state)
        c_hp      = state["challenger_hp"]
        o_hp      = state["opponent_hp"]
        chat_id   = state["chat_id"]

        status = _battle_status(state)

        if c_hp <= 0 or o_hp <= 0:
            await query.edit_message_text(
                f"{status}\n{round_log}",
                parse_mode="Markdown",
            )
            await _finish_battle(context, chat_id, state, pid)
        else:
            await query.edit_message_text(
                f"{status}\n{round_log}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"⚔️ Round {state['round']}",
                        callback_data=f"{pid}_fight",
                    ),
                ]]),
            )