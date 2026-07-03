"""Ручной запуск пайплайна торгового брифинга (без бота)."""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import Settings
from src.report.generator import ReportGenerationError, generate_report
from src.report.storage import SavedReport, persist_report_result

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def run_pipeline():
    from src.calendar.investing import collect_economic_calendar
    from src.data.sheets import load_portfolio_analytics
    from src.news.aggregator import collect_news
    from src.structure.aggregation import load_structure_analysis

    settings = Settings()
    print("1/4 Загрузка портфеля из Google Sheets...")
    analytics = load_portfolio_analytics(settings)
    print(
        f"    ETF: {len(analytics.positions)}, "
        f"стоимость: {analytics.total_volume:,.0f} EUR"
    )

    print("2/4 Загрузка структуры ETF...")
    structure = await load_structure_analysis(analytics)
    print(
        f"    Бумаг портфеля: {len(structure.portfolio_holdings)}, "
        f"watchlist: {len(structure.watchlist_tracking_holdings)}"
    )

    print("3/4 Сбор новостей и календаря...")
    calendar = await collect_economic_calendar(days_ahead=1)
    news = await collect_news(analytics, settings, structure=structure)
    print(f"    Новостей: {len(news)}, событий календаря: {len(calendar)}")

    print("4/4 Генерация брифинга через OpenAI...")
    return await generate_report(
        analytics,
        news,
        settings,
        structure=structure,
        calendar=calendar,
    )


async def main():
    try:
        result = await run_pipeline()
    except ReportGenerationError as exc:
        print(f"[FAIL] {exc}")
        return 1
    except Exception as exc:
        logging.exception("Ошибка пайплайна")
        print(f"[FAIL] {exc}")
        return 1

    saved = persist_report_result(result)
    if saved is None:
        saved = SavedReport(
            markdown=result.markdown,
            metadata=result.metadata,
            directory=Path("."),
            md_path=Path("."),
            pdf_path=None,
        )

    print("=" * 60)
    print(f"Markdown: {saved.md_path.resolve()}")
    if saved.pdf_path and saved.pdf_path.is_file():
        size_kb = saved.pdf_path.stat().st_size // 1024
        print(f"PDF:      {saved.pdf_path.resolve()} ({size_kb} KB)")
    print(f"Модель:   {result.metadata.ai_model}")
    print(f"Новостей: {result.metadata.news_total}")
    print("=" * 60)
    preview = result.markdown[:2500]
    print(preview)
    if len(result.markdown) > 2500:
        print(f"\n... (ещё {len(result.markdown) - 2500} символов в файле)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
