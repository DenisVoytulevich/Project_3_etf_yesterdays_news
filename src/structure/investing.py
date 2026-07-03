from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.structure.models import InstrumentQuote, InvestingDataError

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.investing.com/api/search/v2/search"
INSTRUMENT_URL = "https://endpoints.investing.com/pd-instruments/v1/instruments/{instrument_id}"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

EUR_EXCHANGE_PRIORITY = (
    "Xetra",
    "Frankfurt",
    "Amsterdam",
    "Paris",
    "Milan",
    "Madrid",
    "Vienna",
    "Brussels",
    "Lisbon",
    "Helsinki",
    "Dublin",
)

ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def normalize_isin(isin: str) -> str:
    normalized = isin.strip().upper()
    if not ISIN_PATTERN.match(normalized):
        raise InvestingDataError(f"Некорректный ISIN: {isin}")
    return normalized


def _is_etf_quote(quote: dict[str, Any]) -> bool:
    quote_type = (quote.get("type") or "").upper()
    return "ETF" in quote_type


def _exchange_rank(exchange: str) -> int:
    try:
        return EUR_EXCHANGE_PRIORITY.index(exchange)
    except ValueError:
        return len(EUR_EXCHANGE_PRIORITY)


def _pick_listing(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    etf_quotes = [q for q in quotes if _is_etf_quote(q)]
    if not etf_quotes:
        raise InvestingDataError("По ISIN не найдены ETF на Investing.com")
    etf_quotes.sort(key=lambda q: (_exchange_rank(q.get("exchange", "")), q.get("id", 0)))
    return etf_quotes[0]


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    response = await client.get(url, params=params)
    if response.status_code >= 400:
        raise InvestingDataError(f"Investing.com вернул HTTP {response.status_code} для {url}")
    return response.json()


async def search_by_isin(client: httpx.AsyncClient, isin: str) -> list[dict[str, Any]]:
    data = await _get_json(client, SEARCH_URL, params={"q": isin, "limit": 30})
    return data.get("quotes") or []


async def fetch_instrument(client: httpx.AsyncClient, instrument_id: int) -> dict[str, Any]:
    url = INSTRUMENT_URL.format(instrument_id=instrument_id)
    return await _get_json(client, url)


def _extract_price(instrument: dict[str, Any]) -> tuple[float, str]:
    price_block = instrument.get("price") or {}
    market_open = bool(instrument.get("open"))
    last = price_block.get("last")
    last_close = price_block.get("last_close_value")
    if market_open and last is not None:
        return float(last), "last"
    if last is not None:
        return float(last), "last"
    if last_close is not None:
        return float(last_close), "last_close"
    raise InvestingDataError("Цена инструмента недоступна на Investing.com")


async def _fx_rate_to_eur(client: httpx.AsyncClient, currency: str) -> float:
    currency = currency.upper()
    if currency == "EUR":
        return 1.0

    direct_quotes = await search_by_isin(client, f"{currency}/EUR")
    for quote in direct_quotes:
        if "FX" not in (quote.get("type") or "").upper():
            continue
        instrument = await fetch_instrument(client, int(quote["id"]))
        if (instrument.get("currency_code") or "").upper() == "EUR":
            rate = instrument.get("price", {}).get("last")
            if rate:
                return float(rate)

    inverse_quotes = await search_by_isin(client, f"EUR/{currency}")
    for quote in inverse_quotes:
        if "FX" not in (quote.get("type") or "").upper():
            continue
        instrument = await fetch_instrument(client, int(quote["id"]))
        rate = instrument.get("price", {}).get("last")
        if rate and float(rate) != 0:
            return 1.0 / float(rate)

    raise InvestingDataError(f"Не удалось получить курс {currency}/EUR на Investing.com")


async def fetch_instrument_by_isin(
    isin: str,
    *,
    client: httpx.AsyncClient,
) -> InstrumentQuote:
    normalized_isin = normalize_isin(isin)
    quotes = await search_by_isin(client, normalized_isin)
    if not quotes:
        raise InvestingDataError(f"ISIN {normalized_isin} не найден на Investing.com")

    listing = _pick_listing(quotes)
    instrument = await fetch_instrument(client, int(listing["id"]))

    instrument_isin = (instrument.get("ISIN") or "").upper()
    if instrument_isin != normalized_isin:
        raise InvestingDataError(
            f"ISIN не совпадает: запрошен {normalized_isin}, на странице {instrument_isin or '—'}"
        )

    price_original, price_source = _extract_price(instrument)
    currency = (instrument.get("currency_code") or "").upper()
    if not currency:
        raise InvestingDataError("Валюта инструмента не указана на Investing.com")

    fx_rate = await _fx_rate_to_eur(client, currency)
    price_eur = price_original * fx_rate
    name = instrument.get("long_name") or listing.get("description") or ""

    return InstrumentQuote(
        isin=normalized_isin,
        name=name,
        price_original=price_original,
        currency=currency,
        price_eur=price_eur,
        fx_rate_to_eur=None if currency == "EUR" else fx_rate,
        market_open=bool(instrument.get("open")),
        price_source=price_source,
        investing_id=int(listing["id"]),
        exchange=listing.get("exchange", ""),
        symbol=listing.get("symbol", ""),
        url=f"https://www.investing.com{listing.get('url', '')}",
    )
