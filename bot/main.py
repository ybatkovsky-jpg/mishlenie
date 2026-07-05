"""Entry point for the Mishlenie Thinking Trainer Telegram bot."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from core.config import settings
from core.database import create_tables


def setup_logging() -> None:
    """Configure application logging."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        stream=sys.stdout,
    )
    # Suppress verbose library logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)


async def main() -> None:
    """Initialize and start the bot."""
    setup_logging()
    logger = logging.getLogger(__name__)

    # Validate configuration
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set! Check your .env file.")
        sys.exit(1)
    if not settings.deepseek_api_key:
        logger.error("DEEPSEEK_API_KEY is not set! Check your .env file.")
        sys.exit(1)

    # Create database tables
    logger.info("Creating database tables...")
    await create_tables()
    logger.info("Database tables created.")

    # Initialize bot and dispatcher
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Register routers
    from bot.handlers.start import router as start_router
    from bot.handlers.training import router as training_router
    from bot.handlers.feedback import router as feedback_router
    from bot.handlers.combined import router as combined_router
    from bot.handlers.mindfulness import router as mindfulness_router
    from bot.handlers.book import router as book_router

    dp.include_router(start_router)
    dp.include_router(training_router)
    dp.include_router(feedback_router)
    dp.include_router(combined_router)
    dp.include_router(mindfulness_router)
    dp.include_router(book_router)

    # Register bot commands (shows in Telegram menu)
    from aiogram.types import BotCommand, BotCommandScopeDefault

    commands = [
        BotCommand(command="start", description="🔄 Начать/перезапустить тренировку"),
        BotCommand(command="book", description="📚 Обучение по книгам (15 книг)"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("Bot commands registered")

    logger.info("Starting bot polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
