# Тесты Consistency Validator.

from datetime import datetime
from zoneinfo import ZoneInfo

from src.data.models import PortfolioAnalytics
from src.pipeline.models import BriefingDates, BriefingDraft, FocusContext
from src.pipeline.stages.consistency import run_consistency_validator
from src.structure.aggregation import StructureAnalysis


def _minimal_focus(sectors: list[str]) -> FocusContext:
    local = datetime(2026, 7, 6, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    return FocusContext(
        analytics=PortfolioAnalytics(),
        structure=StructureAnalysis(),
        screening_sectors=sectors,
        companies_context="",
        interest_sectors_context="",
        calendar_context="",
        dates=BriefingDates(
            local=local,
            trading_date="6 июля 2026",
            yesterday_date="5 июля 2026",
            report_datetime="6 июля 2026, 09:00",
            tz_name="Europe/Warsaw",
        ),
    )


def test_consistency_accepts_valid_impact_scores():
    draft = BriefingDraft(
        sections={
            "executive_summary": "Рынки в смешанном тоне.",
            "top_market_news": (
                "| # | Событие | Сила | Сектор | Драйвер сектора |\n"
                "|---|---------|------|--------|------------------|\n"
                "| 1 | Тест нефти | −3 | Airlines | Цена топлива: снижение |"
            ),
            "sector_ratings": (
                "| # | Отрасль | Влияние | Обоснование |\n"
                "|---|---------|---------|-------------|\n"
                "| 1 | Banks | +2 | Позитив по марже |\n"
                "| 2 | Energy | −1 | Слабый сигнал |"
            ),
            "portfolio_companies_news": (
                "| Компания | Зона | Отрасль | Новость | Влияние |\n"
                "|---|---|---|---|---|\n"
                "| — | — | — | Значимых новостей по компаниям списка не выявлено | — |"
            ),
            "key_risks_today": (
                "| Время | Событие | Тип | Влияние | На что влияет |\n"
                "|---|---|---|---|---|\n"
                "| 14:30 | CPI US | Макро | +4 | Banks |"
            ),
        }
    )
    result = run_consistency_validator(draft, _minimal_focus(["Banks", "Energy"]))
    assert not result.issues


def test_consistency_flags_impact_out_of_range():
    draft = BriefingDraft(
        sections={
            "executive_summary": "Тест.",
            "top_market_news": "—",
            "sector_ratings": (
                "| # | Отрасль | Влияние | Обоснование |\n"
                "|---|---------|---------|-------------|\n"
                "| 1 | Banks | +9 | Ошибка |"
            ),
            "portfolio_companies_news": "| — | — | — | Значимых новостей по компаниям списка не выявлено | — |",
            "key_risks_today": "| 10:00 | Test | Макро | +2 | Banks |",
        }
    )
    result = run_consistency_validator(draft, _minimal_focus(["Banks"]))
    codes = {issue.code for issue in result.issues}
    assert "impact_out_of_range" in codes
