from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from src.structure.models import EtfAllocation, EtfHolding, EtfHoldings, InvestingDataError

from src.structure.limits import holdings_top_limit

INVESTING_BASE = "https://www.investing.com"
NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)
OTHER_NAME_PATTERN = re.compile(
    r"^(other|others|прочие|прочее|miscellaneous|rest|andere|autres)$",
    re.IGNORECASE,
)


def build_holdings_page_url(instrument_url: str) -> str:
    parsed = urlparse(instrument_url)
    path = parsed.path
    if not path.startswith("/etfs/"):
        raise InvestingDataError(f"Неподдерживаемый путь ETF: {path}")

    slug = path.rsplit("/", 1)[-1]
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug.endswith("-holdings"):
        slug = f"{slug}-holdings"

    query = urlencode(parse_qs(parsed.query), doseq=True)
    holdings_path = f"/etfs/{slug}"
    return f"{INVESTING_BASE}{holdings_path}?{query}" if query else f"{INVESTING_BASE}{holdings_path}"


def _is_other_label(name: str) -> bool:
    cleaned = name.strip()
    if not cleaned:
        return True
    return bool(OTHER_NAME_PATTERN.match(cleaned))


def _load_holdings_state(html: str) -> dict[str, Any]:
    match = NEXT_DATA_PATTERN.search(html)
    if not match:
        raise InvestingDataError("Данные состава ETF не найдены на странице Investing.com")
    return json.loads(match.group(1))["props"]["pageProps"]["state"]


def _parse_top_holdings(state: dict[str, Any]) -> list[EtfHolding]:
    holdings_store = state.get("holdingsStore") or {}
    holdings_block = holdings_store.get("holdings") or {}
    top_holdings = holdings_block.get("topHoldings") or {}
    collection = top_holdings.get("_collection") or []
    if not isinstance(collection, list):
        return []

    holdings: list[EtfHolding] = []
    for item in collection:
        name = (item.get("name") or item.get("title") or "").strip()
        if not name or _is_other_label(name):
            continue
        weight = item.get("weight")
        if weight is None:
            continue
        holdings.append(
            EtfHolding(
                name=name,
                symbol=(item.get("symbol") or "").strip(),
                weight_pct=round(float(weight), 4),
            )
        )

    holdings.sort(key=lambda h: h.weight_pct, reverse=True)
    limit = holdings_top_limit()
    return holdings[:limit]


def _parse_allocation_breakdown(state: dict[str, Any], key: str) -> list[EtfAllocation]:
    allocations_data = (state.get("holdingsStore") or {}).get("allocationsData") or {}
    raw_items = allocations_data.get(key) or []
    if not isinstance(raw_items, list):
        return []

    allocations: list[EtfAllocation] = []
    for item in raw_items:
        name = (item.get("type") or item.get("name") or item.get("fieldname") or "").strip()
        if not name or _is_other_label(name):
            continue
        weight = item.get("finalValue")
        if weight is None:
            weight = item.get("val") or item.get("value")
        if weight is None:
            continue
        allocations.append(EtfAllocation(name=name, weight_pct=round(float(weight), 4)))

    allocations.sort(key=lambda a: a.weight_pct, reverse=True)
    return allocations


def parse_etf_holdings_page(html: str) -> tuple[list[EtfHolding], list[EtfAllocation], list[EtfAllocation]]:
    state = _load_holdings_state(html)
    holdings = _parse_top_holdings(state)
    regions = _parse_allocation_breakdown(state, "stockRegionData")
    sectors = _parse_allocation_breakdown(state, "stockSectorData")
    return holdings, regions, sectors


async def fetch_etf_holdings(
    *,
    isin: str,
    investing_id: int,
    instrument_url: str,
    client: httpx.AsyncClient,
) -> EtfHoldings:
    holdings_url = build_holdings_page_url(instrument_url)
    response = await client.get(holdings_url, follow_redirects=True)
    if response.status_code >= 400:
        raise InvestingDataError(f"Страница состава ETF недоступна (HTTP {response.status_code})")

    holdings, regions, sectors = parse_etf_holdings_page(response.text)
    if not holdings and not regions and not sectors:
        raise InvestingDataError("Данные состава ETF пусты или недоступны на Investing.com")

    return EtfHoldings(
        isin=isin,
        investing_id=investing_id,
        holdings=holdings,
        regions=regions,
        sectors=sectors,
        total_weight_pct=round(sum(h.weight_pct for h in holdings), 4),
        regions_total_weight_pct=round(sum(r.weight_pct for r in regions), 4),
        sectors_total_weight_pct=round(sum(s.weight_pct for s in sectors), 4),
        source_url=holdings_url,
        top_holdings_limit=holdings_top_limit(),
    )
