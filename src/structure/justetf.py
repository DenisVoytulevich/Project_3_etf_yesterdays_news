from __future__ import annotations

import logging
import re
from html import unescape

import httpx

from src.structure.models import EtfAllocation, EtfHolding, EtfHoldings, InvestingDataError

logger = logging.getLogger(__name__)

from src.structure.limits import holdings_top_limit

JUSTETF_PROFILE_URL = "https://www.justetf.com/en/etf-profile.html?isin={isin}"

_HOLDING_ROW_RE = re.compile(
    r'data-testid="etf-holdings_top-holdings_row".*?'
    r'data-testid="tl_etf-holdings_top-holdings_link_name"[^>]*href="([^"]*)"[^>]*title="([^"]*)"'
    r'.*?data-testid="tl_etf-holdings_top-holdings_value_percentage">([0-9.]+)%',
    re.DOTALL,
)
_SECTOR_ROW_RE = re.compile(
    r'data-testid="tl_etf-holdings_sectors_value_name">([^<]+)</td>.*?'
    r'data-testid="tl_etf-holdings_sectors_value_percentage">([0-9.]+)%',
    re.DOTALL,
)
_OTHER_SECTOR_RE = re.compile(r"^(other|others|прочие|прочее)$", re.IGNORECASE)


def _symbol_from_profile_href(href: str) -> str:
    slug = href.rstrip("/").rsplit("/", 1)[-1].upper()
    if slug.startswith("PL") and len(slug) == 12:
        return slug[2:5]
    return slug[:12]


def parse_justetf_profile(html: str) -> tuple[list[EtfHolding], list[EtfAllocation]]:
    holdings: list[EtfHolding] = []
    for match in _HOLDING_ROW_RE.finditer(html):
        href, name, weight = match.groups()
        name = unescape(name).strip()
        if not name:
            continue
        holdings.append(
            EtfHolding(
                name=name,
                symbol=_symbol_from_profile_href(href),
                weight_pct=round(float(weight), 4),
            )
        )

    sectors: list[EtfAllocation] = []
    for match in _SECTOR_ROW_RE.finditer(html):
        name, weight = match.groups()
        name = unescape(name).strip()
        if not name or _OTHER_SECTOR_RE.match(name):
            continue
        sectors.append(EtfAllocation(name=name, weight_pct=round(float(weight), 4)))

    sectors.sort(key=lambda s: s.weight_pct, reverse=True)
    holdings.sort(key=lambda h: h.weight_pct, reverse=True)
    limit = holdings_top_limit()
    return holdings[:limit], sectors


async def fetch_etf_holdings_from_justetf(
    isin: str,
    *,
    client: httpx.AsyncClient,
) -> EtfHoldings:
    normalized = isin.strip().upper()
    url = JUSTETF_PROFILE_URL.format(isin=normalized)
    response = await client.get(url, follow_redirects=True)
    if response.status_code >= 400:
        raise InvestingDataError(f"justETF вернул HTTP {response.status_code} для {normalized}")

    holdings, sectors = parse_justetf_profile(response.text)
    if not holdings and not sectors:
        raise InvestingDataError(f"Состав ETF {normalized} не найден на justETF")

    return EtfHoldings(
        isin=normalized,
        investing_id=0,
        holdings=holdings,
        regions=[],
        sectors=sectors,
        total_weight_pct=round(sum(h.weight_pct for h in holdings), 4),
        sectors_total_weight_pct=round(sum(s.weight_pct for s in sectors), 4),
        source_url=url,
        top_holdings_limit=holdings_top_limit(),
    )
