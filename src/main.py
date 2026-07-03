import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot.handlers import BriefingService, create_bot_handlers, send_briefing_to_chat
from src.bot.scheduler import setup_scheduler
from src.config import Settings
from src.report.generator import ReportGenerationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()
    service = BriefingService(settings)

    dp.include_router(create_bot_handlers(service, settings))

    async def daily_briefing_job() -> None:
        logger.info("Запуск ежедневного торгового брифинга")
        try:
            await bot.send_message(
                settings.telegram_chat_id,
                "📊 Формирую утренний торговый брифинг (новости вчера + календарь сегодня)...",
            )
            saved = await service.execute()
            await send_briefing_to_chat(bot, settings, saved)
            logger.info("Ежедневный брифинг отправлен")
        except ReportGenerationError as exc:
            logger.error("Брифинг не сформирован: %s", exc)
            await bot.send_message(
                settings.telegram_chat_id,
                f"❌ Брифинг не сформирован: {exc}",
            )
        except Exception:
            logger.exception("Ошибка ежедневного брифинга")
            await bot.send_message(
                settings.telegram_chat_id,
                "❌ Не удалось сформировать брифинг. Проверьте логи.",
            )

    scheduler = setup_scheduler(settings, daily_briefing_job)
    scheduler.start()

    logger.info("Бот ETF Daily Briefing запущен")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
