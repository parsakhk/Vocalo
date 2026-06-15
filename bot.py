import os
import logging
from telegram import Update
from telegram.error import TimedOut, NetworkError
from dotenv import load_dotenv

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from handlers.start      import start_handler
from handlers.enable     import enable_handler
from handlers.messages   import message_handler
from handlers.inventory  import inventory_handler
from handlers.forcespawn import forcespawn_handler
from handlers.profile    import profile_handler
from handlers.signin     import signin_handler

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
    app.add_handler(CommandHandler("inventory",  inventory_handler))
    app.add_handler(CommandHandler("forcespawn", forcespawn_handler))
    app.add_handler(CommandHandler("profile",    profile_handler))
    app.add_handler(CommandHandler("signin",     signin_handler))

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