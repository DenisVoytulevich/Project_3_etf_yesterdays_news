from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src.structure.models import EtfAllocation, EtfHolding, EtfHoldings

logger = logging.getLogger(__name__)


def _holdings_to_dict(data: EtfHoldings) -> dict:
    return {
        "isin": data.isin,
        "investing_id": data.investing_id,
        "holdings": [asdict(h) for h in data.holdings],
        "regions": [asdict(r) for r in data.regions],
        "sectors": [asdict(s) for s in data.sectors],
        "total_weight_pct": data.total_weight_pct,
        "regions_total_weight_pct": data.regions_total_weight_pct,
        "sectors_total_weight_pct": data.sectors_total_weight_pct,
        "source_url": data.source_url,
        "top_holdings_limit": data.top_holdings_limit,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }


def _holdings_from_dict(payload: dict) -> EtfHoldings:
    return EtfHoldings(
        isin=payload["isin"],
        investing_id=int(payload["investing_id"]),
        holdings=[EtfHolding(**h) for h in payload.get("holdings", [])],
        regions=[EtfAllocation(**r) for r in payload.get("regions", [])],
        sectors=[EtfAllocation(**s) for s in payload.get("sectors", [])],
        total_weight_pct=float(payload.get("total_weight_pct", 0)),
        regions_total_weight_pct=float(payload.get("regions_total_weight_pct", 0)),
        sectors_total_weight_pct=float(payload.get("sectors_total_weight_pct", 0)),
        source_url=payload.get("source_url", ""),
        top_holdings_limit=int(payload.get("top_holdings_limit", 10)),
    )


def _cache_path(cache_dir: Path, isin: str) -> Path:
    return cache_dir / f"{isin.upper()}.json"


def load_cached_holdings(cache_dir: Path, isin: str, ttl_hours: float) -> EtfHoldings | None:
    path = _cache_path(cache_dir, isin)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(payload["cached_at"])
        age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
        if age_hours > ttl_hours:
            return None
        return _holdings_from_dict(payload)
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Битый кэш %s: %s", path, exc)
        return None


def save_cached_holdings(cache_dir: Path, data: EtfHoldings) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, data.isin)
    path.write_text(json.dumps(_holdings_to_dict(data), ensure_ascii=False, indent=2), encoding="utf-8")
