from dataclasses import dataclass, field


@dataclass
class EtfPosition:
    ticker: str
    name: str
    volume: float
    sector: str
    region: str
    weight: float = 0.0
    isin: str = ""
    group: str = ""
    value_eur: float = 0.0


def position_market_value(pos: EtfPosition) -> float:
    """Стоимость позиции в EUR; без котировки — fallback на QTY."""
    return pos.value_eur if pos.value_eur > 0 else pos.volume


@dataclass
class InterestZoneItem:
    """Строка зоны интереса Watchlist: отрасль и/или инструмент."""

    sector: str
    isin: str
    name: str
    ticker: str = ""


@dataclass
class WatchItem:
    ticker: str
    name: str
    sector: str
    region: str
    note: str = ""


@dataclass
class SectorInterest:
    sector: str
    priority: int = 1


@dataclass
class SectorShare:
    sector: str
    volume: float
    share_pct: float


@dataclass
class RegionShare:
    region: str
    volume: float
    share_pct: float


@dataclass
class PortfolioAnalytics:
    positions: list[EtfPosition] = field(default_factory=list)
    interest_zone: list[InterestZoneItem] = field(default_factory=list)
    watchlist: list[WatchItem] = field(default_factory=list)
    sector_interests: list[SectorInterest] = field(default_factory=list)
    top_holdings: list[EtfPosition] = field(default_factory=list)
    sector_shares: list[SectorShare] = field(default_factory=list)
    region_shares: list[RegionShare] = field(default_factory=list)
    total_volume: float = 0.0

    @property
    def tickers(self) -> list[str]:
        return [p.ticker for p in self.positions]

    @property
    def watch_tickers(self) -> list[str]:
        tickers = [i.ticker for i in self.interest_zone if i.ticker]
        if tickers:
            return tickers
        return [w.ticker for w in self.watchlist]

    @property
    def interest_sectors(self) -> list[str]:
        sectors = [s.sector for s in self.sector_interests]
        for item in self.interest_zone:
            if not item.isin and item.sector and item.sector != "—":
                sectors.append(item.sector)
        return sectors
