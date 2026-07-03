import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from src.bot.keyboards import MANUAL_REPORT_BUTTON, main_keyboard
from src.config import Settings, load_yaml_config
from src.report.generator import ReportGenerationError
from src.report.storage import ReportResult, SavedReport, persist_report_result

logger = logging.getLogger(__name__)

router = Router()


def _split_message(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


class BriefingService:
    """Оркестратор: портфель → структура → новости → брифинг."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._running = False

    async def run_pipeline(self) -> ReportResult:
        from src.calendar.investing import collect_economic_calendar
        from src.data.sheets import load_portfolio_analytics
        from src.news.aggregator import collect_news
        from src.report.generator import generate_report
        from src.structure.aggregation import load_structure_analysis

        analytics = load_portfolio_analytics(self.settings)
        structure = await load_structure_analysis(analytics)
        calendar = await collect_economic_calendar(days_ahead=1)
        news = await collect_news(analytics, self.settings, structure=structure)
        return await generate_report(
            analytics,
            news,
            self.settings,
            structure=structure,
            calendar=calendar,
        )

    @property
    def is_running(self) -> bool:
        return self._running

    async def execute(self) -> SavedReport:
        if self._running:
            raise RuntimeError("Сервис уже выполняется")
        self._running = True
        try:
            result = await self.run_pipeline()
            saved = persist_report_result(result)
            if saved is not None:
                return saved
            return SavedReport(
                markdown=result.markdown,
                metadata=result.metadata,
                directory=Path("."),
                md_path=Path("."),
                pdf_path=None,
            )
        finally:
            self._running = False


async def send_briefing_to_chat(bot: Bot, settings: Settings, saved: SavedReport) -> None:
    yaml_cfg = load_yaml_config()
    max_msg = yaml_cfg.get("telegram_max_message", 4000)
    caption = (
        f"Торговый брифинг · {saved.metadata.trading_date} "
        f"(новости за {saved.metadata.yesterday_date})"
    )

    if saved.pdf_path and saved.pdf_path.is_file():
        await bot.send_document(
            settings.telegram_chat_id,
            FSInputFile(
                saved.pdf_path,
                filename=saved.metadata.pdf_file or saved.pdf_path.name,
            ),
            caption=caption,
        )
        return

    chunks = _split_message(saved.markdown, max_msg)
    for i, chunk in enumerate(chunks):
        await bot.send_message(
            settings.telegram_chat_id,
            chunk,
            parse_mode="Markdown" if i == 0 else None,
        )


async def run_manual_briefing(message: Message, service: BriefingService, settings: Settings) -> None:
    if service.is_running:
        await message.answer("Сервис уже собирает данные, подождите...")
        return

    await message.answer("⏳ Запускаю сбор новостей и формирование брифинга...")
    try:
        saved = await service.execute()
        await send_briefing_to_chat(message.bot, settings, saved)
    except ReportGenerationError as exc:
        logger.error("Брифинг не сформирован: %s", exc)
        await message.answer(f"Брифинг не сформирован: {exc}")
    except Exception as exc:
        logger.exception("Ошибка формирования брифинга")
        await message.answer(f"Ошибка: {exc}")


def create_bot_handlers(service: BriefingService, settings: Settings) -> Router:
    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "ETF Daily Briefing\n\n"
            "Ежедневный торговый брифинг: новости вчера + календарь сегодня.\n\n"
            "Команды:\n"
            "/report — брифинг по запросу (кнопка ниже)\n"
            "/status — режим работы\n"
            "/portfolio — краткая сводка портфеля\n\n"
            f"Автоотчёт: каждый день в "
            f"{settings.daily_briefing_hour:02d}:{settings.daily_briefing_minute:02d} "
            f"({settings.timezone}).",
            reply_markup=main_keyboard(),
        )

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        running = "выполняется" if service.is_running else "ожидание"
        await message.answer(
            f"Сервис: {running}\n"
            f"Часовой пояс: {settings.timezone}\n"
            f"Автоотчёт: {settings.daily_briefing_hour:02d}:"
            f"{settings.daily_briefing_minute:02d}\n"
            "Ручной запуск: в любое время (/report или кнопка)"
        )

    @router.message(Command("portfolio"))
    async def cmd_portfolio(message: Message) -> None:
        try:
            from src.data.models import position_market_value
            from src.data.sheets import load_portfolio_analytics
            from src.structure.aggregation import load_structure_analysis

            analytics = load_portfolio_analytics(settings)
            await load_structure_analysis(analytics)
            lines = [
                f"📊 Портфель: {len(analytics.positions)} ETF",
                f"Стоимость: {analytics.total_volume:,.0f} EUR",
                "",
                "Топ-5 по стоимости:",
            ]
            for position in analytics.top_holdings[:5]:
                lines.append(
                    f"• {position.ticker} — "
                    f"{position_market_value(position):,.0f} EUR ({position.weight:.1f}%)"
                )
            lines.append("")
            lines.append("Отрасли:")
            for sector in analytics.sector_shares[:5]:
                lines.append(f"• {sector.sector}: {sector.share_pct:.1f}%")
            await message.answer("\n".join(lines))
        except Exception as exc:
            logger.exception("Ошибка загрузки портфеля")
            await message.answer(f"Ошибка: {exc}")

    @router.message(Command("report"))
    @router.message(F.text == MANUAL_REPORT_BUTTON)
    async def cmd_report(message: Message) -> None:
        await run_manual_briefing(message, service, settings)

    return router
