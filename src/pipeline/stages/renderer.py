"""Renderer: финальная сборка Markdown/HTML/PDF."""

from __future__ import annotations

import logging
from datetime import timezone

from src.config import Settings
from src.pipeline.models import FocusContext, NewsBatch, ValidatedBriefing
from src.report.generator import render_report
from src.report.html import render_html_report
from src.report.storage import ReportMetadata, ReportResult

logger = logging.getLogger(__name__)


def run_renderer(
    validated: ValidatedBriefing,
    batch: NewsBatch,
    focus: FocusContext,
    settings: Settings,
) -> ReportResult:
    markdown = render_report(
        batch.items,
        validated.sections,
        trading_date=focus.dates.trading_date,
        yesterday_date=focus.dates.yesterday_date,
        report_datetime=focus.dates.report_datetime,
        ai_model=validated.model or settings.openai_model,
    )
    html = render_html_report(
        validated.sections,
        trading_date=focus.dates.trading_date,
        yesterday_date=focus.dates.yesterday_date,
        report_datetime=focus.dates.report_datetime,
        news_count=len(batch.items),
        ai_model=validated.model or settings.openai_model,
    )
    logger.info(
        "Renderer: markdown %d символов, html %d символов",
        len(markdown),
        len(html),
    )

    metadata = ReportMetadata(
        id=focus.dates.local.strftime("%Y-%m-%d_%H%M%S"),
        created_at=focus.dates.local.astimezone(timezone.utc).isoformat(),
        trading_date=focus.dates.trading_date,
        yesterday_date=focus.dates.yesterday_date,
        ai_model=validated.model or settings.openai_model,
        portfolio_count=len(focus.analytics.positions),
        news_total=len(batch.items),
        watchlist_count=len(focus.structure.watchlist_sectors) if focus.structure else 0,
        calendar_events=len(focus.calendar_events),
        screening_sectors=len(focus.screening_sectors),
    )
    return ReportResult(markdown=markdown, metadata=metadata, html=html)
