"""
Trade command — multi-step inline keyboard flow.

Flow:
  1. /trade @username  → initiator picks characters (paginated)
  2. Initiator confirms their offer (optionally adds VP)
  3. Receiver picks their characters + VP
  4. Receiver confirms → trade executes
"""

import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes, CallbackQueryHandler
from db.client import get_db
from db.queries import get_or_create_user, get_user

ITEMS_PER_PAGE = 5

# In-memory trade sessions  { trade_id: TradeState }
_trades: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_inventory(telegram_id: int) -> list[dict]:
    db = get_db()
    res = (
        db.table("inventory")
        .select("id, caught_price, rarity, characters(name, anime)")
        .eq("telegram_id", telegram_id)
        .order("caught_price", desc=True)
        .execute()
    )
    return res.data


def _trade_id(initiator_id: int, receiver_id: int) -> str:
    return f"trade_{initiator_id}_{receiver_id}"


def _rarity_emoji(rarity: str) -> str:
    return {"Legendary": "🌟", "Mythic": "💜", "Rare": "💙"}.get(rarity, "⚪")


def _offer_summary(items: list[dict], vp: int, label: str) -> str:
    if not items and vp == 0:
        return f"*{label}:* Nothing yet\n"
    lines = [f"*{label}:*"]
    for item in items:
        char   = item.get("characters") or {}
        name   = char.get("name", "?")
        rarity = item.get("rarity", "Common")
        lines.append(f"  {_rarity_emoji(rarity)} {name}")
    if vp > 0:
        lines.append(f"  💰 {vp:,} VP")
    return "\n".join(lines) + "\n"


def _build_picker_keyboard(
    items: list[dict],
    selected_ids: set[int],
    page: int,
    prefix: str,
) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
    page_items  = items[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

    buttons = []
    for item in page_items:
        char      = item.get("characters") or {}
        name      = char.get("name", "?")
        rarity    = item.get("rarity", "Common")
        inv_id    = item["id"]
        price     = item["caught_price"]
        check     = "✅ " if inv_id in selected_ids else ""
        buttons.append([InlineKeyboardButton(
            f"{check}{_rarity_emoji(rarity)} {name} — {price} VP",
            callback_data=f"{prefix}_toggle:{inv_id}:{page}",
        )])

    # Navigation
    nav = []
    if total_pages > 1:
        nav.append(InlineKeyboardButton("⏮", callback_data=f"{prefix}_page:0"))
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"{prefix}_page:{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data=f"{prefix}_noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"{prefix}_page:{page+1}"))
        nav.append(InlineKeyboardButton("⏭", callback_data=f"{prefix}_page:{total_pages-1}"))
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton("➕ Add VP", callback_data=f"{prefix}_addvp"),
        InlineKeyboardButton("✅ Confirm offer", callback_data=f"{prefix}_confirm"),
    ])
    buttons.append([InlineKeyboardButton("❌ Cancel trade", callback_data=f"{prefix}_cancel")])
    return InlineKeyboardMarkup(buttons)


def _trade_message(trade: dict) -> str:
    init_name = trade["initiator_name"]
    recv_name = trade["receiver_name"]

    text  = "🔄 *Trade in progress*\n\n"
    text += _offer_summary(trade["init_items"],  trade["init_vp"],  f"🧑 {init_name} offers")
    text += "\n"
    text += _offer_summary(trade["recv_items"],  trade["recv_vp"],  f"🧑 {recv_name} offers")
    return text


# ─────────────────────────────────────────────────────────────────────────────
#  /trade command
# ─────────────────────────────────────────────────────────────────────────────

async def trade_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    initiator = update.effective_user
    get_or_create_user(initiator.id, initiator.full_name, initiator.username)

    # Expect /trade @username
    if not context.args:
        await update.message.reply_text(
            "Usage: `/trade @username`",
            parse_mode="Markdown",
        )
        return

    raw = context.args[0].lstrip("@")
    db  = get_db()
    res = db.table("users").select("*").eq("username", raw).execute()

    if not res.data:
        await update.message.reply_text(
            f"⚠️ User @{raw} not found. They need to `/signin` first.",
            parse_mode="Markdown",
        )
        return

    receiver = res.data[0]

    if receiver["telegram_id"] == initiator.id:
        await update.message.reply_text("⚠️ You can't trade with yourself.")
        return

    tid   = _trade_id(initiator.id, receiver["telegram_id"])
    items = _get_inventory(initiator.id)

    if not items:
        await update.message.reply_text("🗂 You have no characters to trade!")
        return

    _trades[tid] = {
        "initiator_id":   initiator.id,
        "initiator_name": initiator.first_name,
        "receiver_id":    receiver["telegram_id"],
        "receiver_name":  receiver.get("full_name", raw),
        "init_items":     [],
        "init_vp":        0,
        "recv_items":     [],
        "recv_vp":        0,
        "init_selected":  set(),
        "recv_selected":  set(),
        "phase":          "init_pick",   # init_pick → recv_pick → done
        "message_id":     None,
    }

    keyboard = _build_picker_keyboard(items, set(), 0, tid)
    msg = await update.message.reply_text(
        f"🔄 *Trade with {receiver.get('full_name', raw)}*\n\n"
        f"Select the characters you want to offer:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    _trades[tid]["message_id"] = msg.message_id


# ─────────────────────────────────────────────────────────────────────────────
#  Callback router
# ─────────────────────────────────────────────────────────────────────────────

async def trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user  = update.effective_user
    await query.answer()

    data = query.data

    # Find the trade this callback belongs to
    trade = None
    tid   = None
    for key, t in _trades.items():
        if data.startswith(key):
            trade = t
            tid   = key
            break

    if not trade:
        await query.edit_message_text("⚠️ This trade session has expired.")
        return

    phase = trade["phase"]

    # Determine whose turn it is
    if phase == "init_pick" and user.id != trade["initiator_id"]:
        await query.answer("It's not your turn!", show_alert=True)
        return
    if phase == "recv_pick" and user.id != trade["receiver_id"]:
        await query.answer("It's not your turn!", show_alert=True)
        return

    # Strip the trade_id prefix to get the action
    action = data[len(tid)+1:]  # e.g. "toggle:123:0"
    parts  = action.split(":")

    cmd    = parts[0]
    is_init = phase == "init_pick"
    selected_key = "init_selected" if is_init else "recv_selected"
    items_key    = "init_items"    if is_init else "recv_items"
    owner_id     = trade["initiator_id"] if is_init else trade["receiver_id"]

    # ── No-op ─────────────────────────────────────────────────────────────────
    if cmd == "noop":
        return

    # ── Cancel ────────────────────────────────────────────────────────────────
    if cmd == "cancel":
        del _trades[tid]
        await query.edit_message_text("❌ Trade cancelled.")
        return

    # ── Page navigation ───────────────────────────────────────────────────────
    if cmd == "page":
        page  = int(parts[1])
        items = _get_inventory(owner_id)
        kb    = _build_picker_keyboard(items, trade[selected_key], page, tid)
        await query.edit_message_reply_markup(reply_markup=kb)
        return

    # ── Toggle character selection ────────────────────────────────────────────
    if cmd == "toggle":
        inv_id = int(parts[1])
        page   = int(parts[2])

        if inv_id in trade[selected_key]:
            trade[selected_key].discard(inv_id)
        else:
            trade[selected_key].add(inv_id)

        items = _get_inventory(owner_id)
        kb    = _build_picker_keyboard(items, trade[selected_key], page, tid)
        await query.edit_message_reply_markup(reply_markup=kb)
        return

    # ── Add VP ────────────────────────────────────────────────────────────────
    if cmd == "addvp":
        vp_key = "init_vp" if is_init else "recv_vp"
        db     = get_db()
        user_res = db.table("users").select("coins").eq("telegram_id", owner_id).execute()
        balance  = user_res.data[0]["coins"] if user_res.data else 0

        context.user_data["awaiting_vp"]  = tid
        context.user_data["vp_key"]       = vp_key
        context.user_data["vp_max"]       = balance
        context.user_data["vp_message_id"] = query.message.message_id

        await query.answer(
            f"Reply to this message with how many VP to add (you have {balance:,} VP)",
            show_alert=True,
        )
        return

    # ── Confirm offer ─────────────────────────────────────────────────────────
    if cmd == "confirm":
        # Resolve selected IDs to full item dicts
        all_items   = _get_inventory(owner_id)
        selected    = [i for i in all_items if i["id"] in trade[selected_key]]
        trade[items_key] = selected

        if phase == "init_pick":
            # Switch to receiver's turn
            trade["phase"] = "recv_pick"
            recv_items     = _get_inventory(trade["receiver_id"])

            if not recv_items:
                # Receiver has no characters — still let them add VP only
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("➕ Add VP", callback_data=f"{tid}_addvp"),
                    InlineKeyboardButton("✅ Confirm offer", callback_data=f"{tid}_confirm"),
                ],[
                    InlineKeyboardButton("❌ Cancel trade", callback_data=f"{tid}_cancel"),
                ]])
            else:
                kb = _build_picker_keyboard(recv_items, set(), 0, tid)

            text = (
                _trade_message(trade) +
                f"\n⏳ *{trade['receiver_name']}*, select what you offer in return:"
            )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

        elif phase == "recv_pick":
            # Both sides confirmed — execute trade
            await _execute_trade(query, trade, tid)

        return


# ─────────────────────────────────────────────────────────────────────────────
#  VP text input handler
# ─────────────────────────────────────────────────────────────────────────────

async def trade_vp_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the VP amount the user types after pressing 'Add VP'."""
    if "awaiting_vp" not in context.user_data:
        return

    tid     = context.user_data["awaiting_vp"]
    vp_key  = context.user_data["vp_key"]
    vp_max  = context.user_data["vp_max"]
    trade   = _trades.get(tid)

    if not trade:
        context.user_data.pop("awaiting_vp", None)
        return

    try:
        amount = int(update.message.text.strip())
        assert 0 < amount <= vp_max
    except (ValueError, AssertionError):
        await update.message.reply_text(
            f"⚠️ Please enter a valid amount between 1 and {vp_max:,}."
        )
        return

    trade[vp_key] = amount
    context.user_data.pop("awaiting_vp", None)

    # Delete the user's VP message to keep chat clean
    try:
        await update.message.delete()
    except Exception:
        pass

    # Refresh the trade keyboard
    is_init  = vp_key == "init_vp"
    owner_id = trade["initiator_id"] if is_init else trade["receiver_id"]
    sel_key  = "init_selected" if is_init else "recv_selected"
    items    = _get_inventory(owner_id)
    kb       = _build_picker_keyboard(items, trade[sel_key], 0, tid)

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=context.user_data.get("vp_message_id"),
        text=(
            f"✅ Added *{amount:,} VP* to your offer.\n\n"
            "Select characters or confirm your offer:"
        ),
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Execute the trade
# ─────────────────────────────────────────────────────────────────────────────

async def _execute_trade(query, trade: dict, tid: str) -> None:
    db = get_db()

    init_id = trade["initiator_id"]
    recv_id = trade["receiver_id"]

    # Check VP balances
    init_bal = db.table("users").select("coins").eq("telegram_id", init_id).execute().data[0]["coins"]
    recv_bal = db.table("users").select("coins").eq("telegram_id", recv_id).execute().data[0]["coins"]

    if trade["init_vp"] > init_bal:
        await query.edit_message_text(
            f"❌ Trade failed — {trade['initiator_name']} doesn't have enough VP.",
        )
        del _trades[tid]
        return

    if trade["recv_vp"] > recv_bal:
        await query.edit_message_text(
            f"❌ Trade failed — {trade['receiver_name']} doesn't have enough VP.",
        )
        del _trades[tid]
        return

    # Transfer characters: reassign telegram_id on each inventory row
    for item in trade["init_items"]:
        db.table("inventory").update({"telegram_id": recv_id}).eq("id", item["id"]).execute()

    for item in trade["recv_items"]:
        db.table("inventory").update({"telegram_id": init_id}).eq("id", item["id"]).execute()

    # Transfer VP
    if trade["init_vp"] > 0:
        db.rpc("increment_coins", {"user_id": init_id, "amount": -trade["init_vp"]}).execute()
        db.rpc("increment_coins", {"user_id": recv_id, "amount":  trade["init_vp"]}).execute()

    if trade["recv_vp"] > 0:
        db.rpc("increment_coins", {"user_id": recv_id, "amount": -trade["recv_vp"]}).execute()
        db.rpc("increment_coins", {"user_id": init_id, "amount":  trade["recv_vp"]}).execute()

    del _trades[tid]

    init_chars = ", ".join(
        (i.get("characters") or {}).get("name", "?") for i in trade["init_items"]
    ) or "nothing"
    recv_chars = ", ".join(
        (i.get("characters") or {}).get("name", "?") for i in trade["recv_items"]
    ) or "nothing"

    await query.edit_message_text(
        f"✅ *Trade complete!*\n\n"
        f"🧑 *{trade['initiator_name']}* gave: {init_chars}"
        + (f" + {trade['init_vp']:,} VP" if trade["init_vp"] else "") + "\n"
        f"🧑 *{trade['receiver_name']}* gave: {recv_chars}"
        + (f" + {trade['recv_vp']:,} VP" if trade["recv_vp"] else ""),
        parse_mode="Markdown",
    )