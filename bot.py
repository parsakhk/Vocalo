import os
import logging
from telegram import Update
from telegram.error import TimedOut, NetworkError
from dotenv import load_dotenv

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from handlers.start      import start_handler
from handlers.enable     import enable_handler
from handlers.disable    import disable_handler
from handlers.messages   import message_handler
from handlers.inventory  import inventory_handler
from handlers.forcespawn import forcespawn_handler
from handlers.profile    import profile_handler
from handlers.signin     import signin_handler
from handlers.sell       import sell_handler, sell_callback
from handlers.trade      import trade_handler, trade_callback, trade_vp_input
from handlers.info       import info_handler, info_callback
from handlers.reforge    import reforge_handler, reforge_callback
from handlers.bet        import bet_handler
from handlers.pvp        import pvp_handler, pvp_callback
from handlers.admin      import admin_handler, admin_callback
from handlers.daily      import getvocalos_handler
from handlers.cod        import cod_handler, cod_callback

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context) -> None:
    if isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning("Network error (will auto-retry): %s", context.error)
        return  # swallow it — polling will retry automatically
    logger.error("Unhandled error: %s", context.error, exc_info=context.error)


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in .env")

    app = (
        ApplicationBuilder()
        .token(token)
        .connect_timeout(30)       # seconds to establish connection
        .read_timeout(30)          # seconds to wait for a response
        .write_timeout(30)         # seconds to wait when sending
        .pool_timeout(30)          # seconds to wait for a connection from the pool
        .build()
    )

    # ── Error handler ─────────────────────────────────────────────────────────
    app.add_error_handler(error_handler)

    # ── Commands ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",      start_handler))
    app.add_handler(CommandHandler("enable",     enable_handler))
    app.add_handler(CommandHandler("disable",    disable_handler))
    app.add_handler(CommandHandler("inventory",  inventory_handler))
    app.add_handler(CommandHandler("forcespawn", forcespawn_handler))
    app.add_handler(CommandHandler("profile",    profile_handler))
    app.add_handler(CommandHandler("signin",     signin_handler))
    app.add_handler(CommandHandler("sell",       sell_handler))
    app.add_handler(CommandHandler("trade",      trade_handler))
    app.add_handler(CommandHandler("info",       info_handler))
    app.add_handler(CommandHandler("reforge",    reforge_handler))
    app.add_handler(CommandHandler("bet",        bet_handler))
    app.add_handler(CommandHandler("pvp",        pvp_handler))
    app.add_handler(CommandHandler("admin",      admin_handler))
    app.add_handler(CommandHandler("getvocalos", getvocalos_handler))
    app.add_handler(CommandHandler("cod",        cod_handler))
    app.add_handler(CallbackQueryHandler(cod_callback, pattern="^cod_buy:"))
    app.add_handler(CallbackQueryHandler(sell_callback,    pattern="^sell_"))
    app.add_handler(CallbackQueryHandler(trade_callback,   pattern="^trade_"))
    app.add_handler(CallbackQueryHandler(info_callback,    pattern="^info_"))
    app.add_handler(CallbackQueryHandler(reforge_callback, pattern="^reforge_"))
    app.add_handler(CallbackQueryHandler(pvp_callback,     pattern="^pvp_"))
    app.add_handler(CallbackQueryHandler(admin_callback,   pattern="^adm_"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        trade_vp_input,
    ))

    # ── All group messages (for rate tracking + catch replies) ────────────────
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    logger.info("Bot is running...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,   # ignore messages sent while bot was offline
    )


if __name__ == "__main__":
    main()