from __future__ import annotations

import re

from src.calendar.macro_format import format_date_russian

CORPORATE_TABLE_HEADER = (
    "| Дата | Компания | Событие | Почему важно | Возможное влияние |\n"
    "|------|----------|---------|--------------|-------------------|"
)

_DONE_DATE_PREFIX = "✓ "
_IMPACT_SENTIMENTS = ("Позитив", "Негатив", "Нейтрально", "Мониторинг")

_COMPLETED_EVENT_MARKERS = (
    "опубликован",
    "опубликована",
    "состоял",
    "состояла",
    "прошёл",
    "прошла",
    "завершён",
    "завершена",
    "объявлен",
    "объявлена",
    "вышел",
    "вышла",
)

_POSITIVE_WORDS = (
    "позитив",
    "поддерж",
    "рост",
    "выше ожидан",
    "beat",
    "surge",
    "gain",
)

_NEGATIVE_WORDS = (
    "негатив",
    "давлен",
    "снижен",
    "ниже ожидан",
    "miss",
    "fall",
    "drop",
    "риск",
)

_TICKER_IN_PARENS_RE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,9})\)\s*$")
_RANGE_RE = re.compile(r"[±−\-+]?\d[\d.,]*\s*[…~\-–—]+\s*[±+\-]?\d[\d.,]*\s*%|±\s*\d")
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$")
_DATE_NUMERIC_RE = re.compile(r"^~?(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?:\s*[–—-]\s*~?(\d{1,2})\.(\d{1,2}))?$")


def _parse_table_row(line: str) -> list[str]:
    inner = line.strip().strip("|")
    return [cell.strip() for cell in inner.split("|")]


def _is_separator(line: str) -> bool:
    return bool(_TABLE_SEP_RE.match(line.strip()))


def extract_corporate_table(text: str) -> str:
    lines = text.strip().splitlines()
    table_lines: list[str] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and "Дата" in stripped and "Компания" in stripped:
            in_table = True
            table_lines = [stripped]
            continue
        if in_table:
            if stripped.startswith("|"):
                table_lines.append(stripped)
            elif table_lines:
                break
    if len(table_lines) >= 2:
        return "\n".join(table_lines)
    return text.strip()


def _humanize_date_cell(value: str) -> str:
    text = value.strip()
    if not text or text in {"—", "-"}:
        return text
    done = text.startswith(_DONE_DATE_PREFIX)
    body = text[len(_DONE_DATE_PREFIX) :] if done else text
    match = _DATE_NUMERIC_RE.match(body.strip())
    if not match:
        return text
    d1, m1 = int(match.group(1)), int(match.group(2))
    if match.group(4) and match.group(5):
        d2, m2 = int(match.group(4)), int(match.group(5))
        from datetime import datetime

        start = format_date_russian(datetime(2000, m1, d1))
        end = format_date_russian(datetime(2000, m2, d2))
        body = f"{start}–{end}"
    else:
        from datetime import datetime

        body = format_date_russian(datetime(2000, m1, d1))
    return f"{_DONE_DATE_PREFIX}{body}" if done else body


def _infer_sentiment(event: str, impact: str) -> str:
    blob = f"{event} {impact}".lower()
    if any(word in blob for word in _NEGATIVE_WORDS):
        return "Негатив"
    if any(word in blob for word in _POSITIVE_WORDS):
        return "Позитив"
    if any(marker in event.lower() for marker in _COMPLETED_EVENT_MARKERS):
        return "Позитив"
    if "мониторинг" in blob or "ожида" in blob:
        return "Мониторинг"
    return "Нейтрально"


def _extract_ticker(company: str) -> str:
    match = _TICKER_IN_PARENS_RE.search(company.strip())
    return match.group(1) if match else ""


def _sentiment_defaults(sentiment: str) -> tuple[str, int]:
    mapping = {
        "Позитив": ("−1…+5%", 65),
        "Негатив": ("−5…+1%", 60),
        "Нейтрально": ("−2…+2%", 55),
        "Мониторинг": ("−2…+2%", 50),
    }
    return mapping.get(sentiment, ("−2…+2%", 55))


def _has_range_and_probability(text: str) -> bool:
    lower = text.lower()
    return bool(_RANGE_RE.search(text)) and "вер." in lower and "%" in text


def _strip_leading_ticker(rest: str, company: str) -> str:
    text = rest.strip()
    ticker = _extract_ticker(company)
    if ticker:
        text = re.sub(rf"^{re.escape(ticker)}\b\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _normalize_impact_cell(company: str, event: str, impact: str) -> str:
    text = " ".join(impact.strip().split())
    if not text or text in {"—", "-"}:
        return text
    text = re.sub(r"^[●•]\s*", "", text)
    for sentiment in _IMPACT_SENTIMENTS:
        if text.lower().startswith(sentiment.lower()):
            rest = text[len(sentiment) :].lstrip(" ·.-")
            normalized = f"{sentiment} · {rest}" if rest else sentiment
            break
    else:
        sentiment = _infer_sentiment(event, text)
        normalized = f"{sentiment} · {text}"

    sentiment, rest = parse_corporate_impact(normalized)
    rest = _strip_leading_ticker(rest, company)
    default_range, default_prob = _sentiment_defaults(sentiment)

    if rest and _RANGE_RE.search(rest):
        if "вер." in rest.lower():
            return f"{sentiment} · {rest}"
        return f"{sentiment} · {rest}, вер. {default_prob}%"

    if _has_range_and_probability(f"{sentiment} · {rest}"):
        return f"{sentiment} · {rest}"

    return f"{sentiment} · {default_range}, вер. {default_prob}%"


def _normalize_event_cell(event: str, date: str) -> tuple[str, str]:
    ev = " ".join(event.strip().split())
    dt = date.strip()
    if not ev:
        return dt, ev
    if dt.startswith(_DONE_DATE_PREFIX):
        return dt, ev
    if any(marker in ev.lower() for marker in _COMPLETED_EVENT_MARKERS):
        if not dt.startswith("~"):
            return f"{_DONE_DATE_PREFIX}{dt}", ev
    return dt, ev


def _truncate(text: str, max_len: int) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[: max_len - 1].rsplit(" ", 1)[0]
    return (cut or cleaned[: max_len - 1]) + "…"


def normalize_corporate_table_rows(table: str) -> str:
    lines = table.splitlines()
    if len(lines) < 2:
        return table

    result = [lines[0], lines[1]]
    for line in lines[2:]:
        if not line.strip().startswith("|"):
            result.append(line)
            continue
        cells = _parse_table_row(line)
        if len(cells) < 5:
            result.append(line)
            continue
        cells[0] = _humanize_date_cell(cells[0])
        cells[0], cells[2] = _normalize_event_cell(cells[2], cells[0])
        cells[1] = _truncate(cells[1], 40)
        cells[2] = _truncate(cells[2], 30)
        cells[3] = _truncate(cells[3], 72)
        cells[4] = _truncate(_normalize_impact_cell(cells[1], cells[2], cells[4]), 52)
        result.append("| " + " | ".join(cells) + " |")
    return "\n".join(result)


def is_corporate_calendar_table(headers: list[str]) -> bool:
    if len(headers) != 5:
        return False
    h = [x.lower().strip() for x in headers]
    return (
        "дата" in h[0]
        and "компания" in h[1]
        and "событие" in h[2]
        and "почему важно" in h[3]
        and "возможное влияние" in h[4]
    )


def parse_corporate_impact(value: str) -> tuple[str, str]:
    text = value.strip()
    for sentiment in _IMPACT_SENTIMENTS:
        prefix = f"{sentiment} ·"
        if text.lower().startswith(prefix.lower()):
            return sentiment, text[len(prefix) :].strip()
        if text.lower() == sentiment.lower():
            return sentiment, ""
    return "Нейтрально", text


def parse_corporate_date(value: str) -> tuple[bool, str]:
    text = value.strip()
    if text.startswith(_DONE_DATE_PREFIX):
        return True, text[len(_DONE_DATE_PREFIX) :].strip()
    return False, text


def format_corporate_section(text: str) -> str:
    table = extract_corporate_table(text)
    if not table:
        return text.strip()
    return normalize_corporate_table_rows(table)
