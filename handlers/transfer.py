"""
/transfer @username — Transfer Vocalo Points to another player.
The bot asks how much, user replies with the amount.
"""
from telegram import Update, ForceReply
from telegram.ext import ContextTypes, MessageHandler, filters
from db.queries import get_or_create_user
from db.client import get_db


async def transfer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.full_name, user.username)

    if not context.args:
        await update.message.reply_text(
            "Usage: `/transfer @username`",
            parse_mode="Markdown",
        )
        return

    raw = context.args[0].lstrip("@")
    db  = get_db()
    res = db.table("users").select("telegram_id, full_name, coins").eq("username", raw).execute()

    if not res.data:
        await update.message.reply_text(
            f"⚠️ کاربر @{raw} پیدا نشد. اول باید `/signin` کنه.",
            parse_mode="Markdown",
        )
        return

    receiver = res.data[0]

    if receiver["telegram_id"] == user.id:
        await update.message.reply_text("⚠️ نمیتونی به خودت VP انتقال بدی!")
        return

    # Fetch sender balance
    sender_res = db.table("users").select("coins").eq("telegram_id", user.id).execute()
    balance    = sender_res.data[0]["coins"] if sender_res.data else 0

    # Store receiver info in user_data for the reply handler
    context.user_data["transfer_to"]      = receiver["telegram_id"]
    context.user_data["transfer_to_name"] = receiver.get("full_name", raw)
    context.user_data["transfer_username"]= raw

    msg = await update.message.reply_text(
        f"💸 *انتقال VP به {receiver.get('full_name', raw)}*\n\n"
        f"👛 موجودی شما: *{balance:,} VP*\n\n"
        f"چقدر میخوای انتقال بدی؟ با **ریپلای به همین پیام** مقدار رو بنویس:",
        parse_mode="Markdown",
        reply_markup=ForceReply(selective=True),
    )

    context.user_data["transfer_prompt_id"] = msg.message_id


async def transfer_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user    = update.effective_user
    message = update.message

    # Only handle if this is a reply to our prompt
    if not message.reply_to_message:
        return

    prompt_id = context.user_data.get("transfer_prompt_id")
    if not prompt_id or message.reply_to_message.message_id != prompt_id:
        return

    receiver_id   = context.user_data.get("transfer_to")
    receiver_name = context.user_data.get("transfer_to_name", "کاربر")

    if not receiver_id:
        return

    # Parse amount
    try:
        amount = int(message.text.strip().replace(",", ""))
        assert amount > 0
    except (ValueError, AssertionError):
        await message.reply_text("⚠️ یه عدد درست وارد کن. مثلاً: `500`", parse_mode="Markdown")
        return

    db  = get_db()
    res = db.table("users").select("coins").eq("telegram_id", user.id).execute()
    balance = res.data[0]["coins"] if res.data else 0

    if amount > balance:
        await message.reply_text(
            f"❌ موجودی کافی نداری!\n\n"
            f"👛 موجودی: *{balance:,} VP*\n"
            f"💸 مقدار انتقال: *{amount:,} VP*",
            parse_mode="Markdown",
        )
        return

    if amount < 1:
        await message.reply_text("⚠️ حداقل مقدار انتقال ۱ VP هست.")
        return

    # Execute transfer
    db.rpc("increment_coins", {"user_id": user.id,    "amount": -amount}).execute()
    db.rpc("increment_coins", {"user_id": receiver_id, "amount":  amount}).execute()

    new_balance = balance - amount

    # Clear transfer state
    context.user_data.pop("transfer_to",         None)
    context.user_data.pop("transfer_to_name",    None)
    context.user_data.pop("transfer_username",   None)
    context.user_data.pop("transfer_prompt_id",  None)

    await message.reply_text(
        f"✅ *انتقال موفق!*\n\n"
        f"💸 *{amount:,} VP* به *{receiver_name}* فرستاده شد\n"
        f"👛 موجودی جدید شما: *{new_balance:,} VP*",
        parse_mode="Markdown",
    )