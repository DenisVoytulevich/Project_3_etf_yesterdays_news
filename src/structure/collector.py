from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from src.config import get_project_root, load_yaml_config
from src.structure.cache import load_cached_holdings, save_cached_holdings
from src.structure.holdings import fetch_etf_holdings
from src.structure.investing import DEFAULT_HEADERS, InvestingDataError, fetch_instrument_by_isin
from src.structure.justetf import fetch_etf_holdings_from_justetf
from src.structure.models import EtfHoldings, InstrumentQuote

logger = logging.getLogger(__name__)


@dataclass
class HoldingsFetchResult:
    holdings: dict[str, EtfHoldings] = field(default_factory=dict)
    quotes: dict[str, InstrumentQuote] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _structure_config() -> dict:
    cfg = load_yaml_config().get("structure", {})
    cache_dir = cfg.get("cache_dir", "data/structure_cache")
    return {
        "enabled": cfg.get("enabled", True),
        "cache_dir": get_project_root() / cache_dir,
        "cache_ttl_hours": float(cfg.get("cache_ttl_hours", 168)),
        "request_delay_sec": float(cfg.get("request_delay_sec", 0.5)),
        "justetf_fallback": cfg.get("justetf_fallback", True),
        "holdings_top_limit": int(cfg.get("holdings_top_limit", 25)),
    }


async def _load_etf_holdings(
    isin: str,
    *,
    client: httpx.AsyncClient,
    quote,
    cfg: dict,
) -> EtfHoldings:
    """Investing.com, при пустом составе — justETF."""
    holdings: EtfHoldings | None = None
    last_error: Exception | None = None

    try:
        holdings = await fetch_etf_holdings(
            isin=isin,
            investing_id=quote.investing_id,
            instrument_url=quote.url,
            client=client,
        )
    except InvestingDataError as exc:
        last_error = exc
        logger.debug("Investing.com состав %s: %s", isin, exc)

    if holdings and holdings.holdings:
        return holdings

    if not cfg.get("justetf_fallback", True):
        if holdings:
            return holdings
        raise last_error or InvestingDataError(f"Состав ETF {isin} недоступен")

    try:
        justetf = await fetch_etf_holdings_from_justetf(isin, client=client)
        if holdings:
            if not holdings.holdings:
                holdings.holdings = justetf.holdings
            if not holdings.sectors:
                holdings.sectors = justetf.sectors
            holdings.total_weight_pct = round(
                sum(h.weight_pct for h in holdings.holdings), 4
            )
            holdings.sectors_total_weight_pct = round(
                sum(s.weight_pct for s in holdings.sectors), 4
            )
            logger.info("Состав %s дополнен из justETF", isin)
            return holdings
        logger.info("Состав загружен из justETF: %s", isin)
        return justetf
    except InvestingDataError as exc:
        if holdings:
            logger.warning("justETF для %s: %s — используем частичные данные Investing", isin, exc)
            return holdings
        raise last_error or exc


async def fetch_holdings_batch(isins: list[str]) -> HoldingsFetchResult:
    """Загрузка состава ETF по ISIN (Investing.com + файловый кэш)."""
    cfg = _structure_config()
    unique = sorted({i.strip().upper() for i in isins if i and i.strip()})
    result = HoldingsFetchResult()

    if not unique:
        return result
    if not cfg["enabled"]:
        for isin in unique:
            result.errors[isin] = "Загрузка структуры отключена в settings.yaml"
        return result

    cache_dir = cfg["cache_dir"]
    ttl = cfg["cache_ttl_hours"]
    to_fetch: list[str] = []

    for isin in unique:
        cached = load_cached_holdings(cache_dir, isin, ttl)
        expected_limit = int(cfg.get("holdings_top_limit", 25))
        if cached and cached.top_holdings_limit < expected_limit:
            logger.info(
                "Кэш %s устарел (лимит %d < %d) — перезагрузка",
                isin,
                cached.top_holdings_limit,
                expected_limit,
            )
            cached = None
        if cached:
            result.holdings[isin] = cached
            logger.debug("Кэш: %s", isin)
        else:
            to_fetch.append(isin)

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=timeout) as client:
        for isin in to_fetch:
            try:
                quote = await fetch_instrument_by_isin(isin, client=client)
                result.quotes[isin] = quote
                holdings = await _load_etf_holdings(
                    isin,
                    client=client,
                    quote=quote,
                    cfg=cfg,
                )
                result.holdings[isin] = holdings
                save_cached_holdings(cache_dir, holdings)
                logger.info("Структура загружена: %s", isin)
            except InvestingDataError as exc:
                result.errors[isin] = str(exc)
                logger.warning("Структура %s: %s", isin, exc)

            if cfg["request_delay_sec"] > 0:
                import asyncio

                await asyncio.sleep(cfg["request_delay_sec"])

        for isin in unique:
            if isin in result.quotes:
                continue
            try:
                result.quotes[isin] = await fetch_instrument_by_isin(isin, client=client)
            except InvestingDataError as exc:
                logger.debug("Котировка %s: %s", isin, exc)

            if cfg["request_delay_sec"] > 0 and isin != unique[-1]:
                import asyncio

                await asyncio.sleep(cfg["request_delay_sec"])

    return result
