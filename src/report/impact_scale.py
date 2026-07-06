"""Единая шкала «Влияние» (−5…+5) для всех секций отчёта."""

from __future__ import annotations

import re

IMPACT_MIN = -5
IMPACT_MAX = 5

IMPACT_SCALE_PROMPT = """## Единая шкала «Влияние» (−5…+5)

Используй **одну шкалу** во всех таблицах, где требуется числовая оценка (§1, §2, §3, §4).
Знак: `+` позитив, `−` негатив. Формат: `+3`, `−2`, `0` (без пробела после знака).

| Значение | Значение |
|----------|----------|
| **±1** | Локальная новость. Влияет на отдельные компании. |
| **±2** | Влияет на одну отрасль. Эффект 1–3 дня. |
| **±3** | Влияет на несколько отраслей. Эффект до нескольких недель. |
| **±4** | Влияет на широкий рынок. Меняет ожидания инвесторов. |
| **±5** | Системное событие. Меняет макроэкономическую картину. |
| **0** | Нет влияния. |

Правила:
- Одинаковое событие в §1 — **одинаковое** значение «Влияние» во всех строках этого события.
- §2 агрегирует сигналы из §1 по отрасли.
- §3: оценка влияния новости на бумагу.
- §4: оценка значимости события календаря для рынка.
"""

_SCORE_RE = re.compile(r"^([+\-−–]?\s*\d+)$")


def parse_impact_score(value: str) -> int | None:
    text = value.strip().replace(" ", "")
    if not text or text in {"—", "-", "н/д", "n/a"}:
        return None
    text = text.replace("−", "-").replace("–", "-")
    match = _SCORE_RE.match(text)
    if not match:
        return None
    raw = match.group(1).replace(" ", "")
    if raw.startswith("+"):
        raw = raw[1:]
    try:
        return int(raw)
    except ValueError:
        return None


def is_valid_impact_score(value: str) -> bool:
    score = parse_impact_score(value)
    return score is not None and IMPACT_MIN <= score <= IMPACT_MAX


def impact_sentiment(value: str) -> str | None:
    score = parse_impact_score(value)
    if score is None:
        return None
    if score > 0:
        return "positive"
    if score < 0:
        return "negative"
    return "neutral"


def format_impact_score(value: str) -> str:
    score = parse_impact_score(value)
    if score is None:
        return value.strip()
    if score > 0:
        return f"+{score}"
    return str(score)
