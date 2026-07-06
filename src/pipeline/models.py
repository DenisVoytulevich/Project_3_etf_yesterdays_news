"""Артефакты мультиагентного пайплайна."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.data.models import PortfolioAnalytics
from src.news.models import NewsItem
from src.structure.aggregation import StructureAnalysis

BRIEFING_SECTION_KEYS = (
    "executive_summary",
    "top_market_news",
    "sector_ratings",
    "portfolio_companies_news",
    "key_risks_today",
)


@dataclass
class BriefingDates:
    local: datetime
    trading_date: str
    yesterday_date: str
    report_datetime: str
    tz_name: str


@dataclass
class FocusContext:
    """Обработчик первичных данных: портфель, структура, зоны интереса."""

    analytics: PortfolioAnalytics
    structure: StructureAnalysis
    screening_sectors: list[str]
    companies_context: str
    interest_sectors_context: str
    calendar_context: str
    dates: BriefingDates
    calendar_events: list[Any] = field(default_factory=list)


@dataclass
class NewsBatch:
    items: list[NewsItem]
    removed_duplicates: int = 0
    removed_by_time: int = 0


@dataclass
class ExtractedArticleEntities:
    news_index: int
    title: str
    companies: list[dict[str, str]]
    etfs: list[str]
    countries: list[str]
    currencies: list[str]
    commodities: list[str]
    events: list[dict[str, str]]


@dataclass
class ExtractedEntities:
    articles: list[ExtractedArticleEntities]


@dataclass
class NormalizedEntity:
    source_news_index: int
    entity_type: str
    raw_name: str
    canonical_name: str
    sector: str = ""
    gics: str = ""
    theme: str = ""
    etf_ticker: str = ""


@dataclass
class NormalizedEntities:
    entities: list[NormalizedEntity]
    theme_notes: list[str] = field(default_factory=list)


@dataclass
class BriefingDraft:
    sections: dict[str, str]
    model: str = ""


@dataclass
class QARemark:
    section: str
    location: str
    issue: str
    suggestion: str
    severity: str = "medium"
    approved: bool = True


@dataclass
class QARemarks:
    remarks: list[QARemark]
    model: str = ""


@dataclass
class ConsistencyIssue:
    code: str
    message: str
    section: str = ""


@dataclass
class ValidatedBriefing:
    sections: dict[str, str]
    issues: list[ConsistencyIssue] = field(default_factory=list)
    model: str = ""


@dataclass
class PipelineArtifacts:
    focus: FocusContext
    news: NewsBatch
    extracted: ExtractedEntities | None = None
    normalized: NormalizedEntities | None = None
    draft: BriefingDraft | None = None
    editor_qa: QARemarks | None = None
    analytics_qa: QARemarks | None = None
    validated: ValidatedBriefing | None = None
