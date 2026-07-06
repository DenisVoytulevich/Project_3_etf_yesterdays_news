"""Ручной запуск мультиагентного пайплайна торгового брифинга (без бота)."""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import Settings
from src.report.generator import ReportGenerationError
from src.report.storage import SavedReport, persist_report_result

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

STAGES = (
    "1/10 Обработчик первичных данных (портфель, структура, зоны интереса)",
    "2/10 News Collector",
    "3/10 Entity Extractor",
    "4/10 Theme Normalizer",
    "5/10 Analyst",
    "6/10 QA-1 Редактор",
    "7/10 QA-2 Аналитика",
    "8/10 Revision Agent",
    "9/10 Consistency Validator",
    "10/10 Renderer (MD/HTML/PDF)",
)


async def run_pipeline():
    from src.calendar.investing import collect_economic_calendar
    from src.pipeline.orchestrator import run_multi_agent_pipeline

    settings = Settings()
    for stage in STAGES:
        print(stage)
    calendar = await collect_economic_calendar(days_ahead=1)
    return await run_multi_agent_pipeline(settings, calendar=calendar)


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
    if result.html and saved.metadata.html_file:
        html_path = saved.directory / saved.metadata.html_file
        if html_path.is_file():
            print(f"HTML:     {html_path.resolve()}")
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
