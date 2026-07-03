from dataclasses import dataclass, field


@dataclass(slots=True)
class EtfHolding:
    name: str
    symbol: str
    weight_pct: float


@dataclass(slots=True)
class EtfAllocation:
    name: str
    weight_pct: float


@dataclass(slots=True)
class EtfHoldings:
    isin: str
    investing_id: int
    holdings: list[EtfHolding] = field(default_factory=list)
    regions: list[EtfAllocation] = field(default_factory=list)
    sectors: list[EtfAllocation] = field(default_factory=list)
    total_weight_pct: float = 0.0
    regions_total_weight_pct: float = 0.0
    sectors_total_weight_pct: float = 0.0
    source_url: str = ""
    top_holdings_limit: int = 10


@dataclass(slots=True)
class InstrumentQuote:
    isin: str
    name: str
    price_original: float
    currency: str
    price_eur: float
    fx_rate_to_eur: float | None
    market_open: bool
    price_source: str
    investing_id: int
    exchange: str
    symbol: str
    url: str


class InvestingDataError(Exception):
    """Ошибка при получении данных с Investing.com."""
