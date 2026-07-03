from dataclasses import dataclass
from datetime import datetime


@dataclass
class EconomicEvent:
    event_at: datetime
    country: str
    currency: str
    name: str
    importance: str  # высокая | средняя | низкая
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None
    category: str | None = None
