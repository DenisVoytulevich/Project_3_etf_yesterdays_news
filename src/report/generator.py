import logging
from pathlib import Path

from jinja2 import Template

from src.agent_version import agent_version
from src.config import Settings, get_project_root
from src.data.models import PortfolioAnalytics
from src.news.models import NewsItem
from src.pipeline.models import BRIEFING_SECTION_KEYS
from src.report.markdown_tables import (
    clean_ai_section,
    ensure_sector_ratings_coverage,
    parse_markdown_table_rows,
)
from src.report.storage import ReportResult
from src.structure.aggregation import StructureAnalysis

logger = logging.getLogger(__name__)

AI_SECTION_KEYS = BRIEFING_SECTION_KEYS

# Обратная совместимость для внешних импортов
_clean_ai_section = clean_ai_section
_parse_markdown_table_rows = parse_markdown_table_rows
_ensure_sector_ratings_coverage = ensure_sector_ratings_coverage


class ReportGenerationError(RuntimeError):
    """Отчёт не сформирован: нет успешного ответа OpenAI."""


def _require_openai(settings: Settings) -> None:
    if not (settings.openai_api_key or "").strip():
        raise ReportGenerationError("OPENAI_API_KEY не задан — отчёт не формируется")


def _load_template(name: str) -> str:
    path = get_project_root() / "templates" / name
    return path.read_text(encoding="utf-8")


def render_report(
    news: list[NewsItem],
    ai_sections: dict[str, str],
    *,
    trading_date: str,
    yesterday_date: str,
    report_datetime: str,
    ai_model: str = "—",
) -> str:
    template_md = _load_template("template.md")
    report_template = Template(template_md)
    return report_template.render(
        trading_date=trading_date,
        yesterday_date=yesterday_date,
        report_datetime=report_datetime,
        news_count=len(news),
        agent_version=agent_version(),
        ai_model=ai_model,
        **{key: ai_sections.get(key, "") for key in AI_SECTION_KEYS},
    )


async def generate_report(
    analytics: PortfolioAnalytics,
    news: list[NewsItem],
    settings: Settings,
    structure: StructureAnalysis | None = None,
    calendar=None,
) -> ReportResult:
    """Формирование брифинга через мультиагентный пайплайн."""
    from src.pipeline.orchestrator import run_multi_agent_pipeline

    _require_openai(settings)
    del analytics, news, structure
    return await run_multi_agent_pipeline(settings, calendar=calendar)
