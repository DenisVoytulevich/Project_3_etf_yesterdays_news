from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class NewsPriority(IntEnum):
    PORTFOLIO = 1
    WATCHLIST = 2
    SECTOR = 3
    GENERAL = 4


@dataclass
class NewsItem:
    title: str
    summary: str
    url: str
    source: str
    published: datetime | None = None
    priority: NewsPriority = NewsPriority.GENERAL
    matched_keywords: list[str] = field(default_factory=list)
    related_tickers: list[str] = field(default_factory=list)
    related_sectors: list[str] = field(default_factory=list)
