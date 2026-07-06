"""Конвертация markdown-отчёта в PDF с полноценными таблицами."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from fpdf import FPDF
from fpdf.enums import TableBordersLayout, TableCellFillMode, WrapMode
from fpdf.fonts import FontFace

from src.report.impact_scale import format_impact_score, impact_sentiment, parse_impact_score

logger = logging.getLogger(__name__)

FONT_REGULAR = "ReportFont"
FONT_STARS = "ReportStars"

_STAR_FONT_PATHS: tuple[Path, ...] = (
    Path(r"C:\Windows\Fonts\seguisym.ttf"),
    Path(r"C:\Windows\Fonts\SegoeUIEmoji.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
)

_HEADING_COLORS = {
    1: (15, 61, 92),
    2: (22, 74, 107),
    3: (42, 95, 127),
}
_HEADING_SIZES = {1: 16, 2: 12, 3: 11}

_FONT_TRIPLETS: tuple[tuple[Path, Path, Path | None], ...] = (
    (
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\ariali.ttf"),
    ),
    (
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\segoeuii.ttf"),
    ),
    (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ),
    (
        Path("/Library/Fonts/Arial.ttf"),
        Path("/Library/Fonts/Arial Bold.ttf"),
        Path("/Library/Fonts/Arial Italic.ttf"),
    ),
)

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\u2600-\u2604"
    "\u2607-\u27BF"
    "\uFE0F"
    "]",
    flags=re.UNICODE,
)
_STAR_FILLED = "\u2605"  # ★
_STAR_EMPTY = "\u2606"  # ☆
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$")
_NUMERIC_RE = re.compile(r"^[\d\s.,+%\-–—]+$")
_RATING_RE = re.compile(r"^[+\-−–]?\d+$")
_HEADING_SCALE_SUFFIX_RE = re.compile(
    r"\s*[\(\（]\s*[−\-–+]?\s*5\s*[…\.\·]{1,3}\s*\+?\s*5\s*[\)\）]\s*$"
)
_REPORT_BOILERPLATE_PREFIXES = (
    "Сбор данных:",
    "Единая шкала «Влияние»",
)

_INDEX_HEADERS = frozenset({"#", "№", "no", "номер"})

_AI_SECTION_MARKERS = frozenset({
    "executive_summary",
    "top_market_news",
    "sector_ratings",
    "portfolio_companies_news",
    "key_risks_today",
})

_TABLE_HEADER_FILL = (198, 208, 220)
_TABLE_BODY_ROW_FILL = (248, 250, 252)
_TABLE_BODY_TEXT_COLOR = (30, 41, 59)
_TABLE_HEADER_SIZE_BOOST = 1.0

# Ширины колонок типовых таблиц (fpdf: веса-пропорции, сумма не обязана быть 1).
_TABLE1_COL_WIDTHS = (4, 34, 10, 19, 33)  # §1: # | Событие | Влияние | Сектор | Драйвер
_TABLE2_COL_WIDTHS = (5, 35, 10, 50)  # §2: # | Отрасль | Влияние | Обоснование
_TABLE3_COL_WIDTHS = (18, 14, 14, 44, 10)  # §3: Компания | Зона | Отрасль | Новость | Влияние
_TABLE4_COL_WIDTHS = (12, 25, 15, 10, 38)  # §4: Время | Событие | Тип | Влияние | На что влияет
_IMPACT_COL_WEIGHT = _TABLE1_COL_WIDTHS[2]  # эталон ширины «Влияние» — как в §1
_REF_TABLE_HEADERS = ("#", "Событие", "Влияние", "Сектор", "Драйвер")

_DRIVER_SENTIMENT_POSITIVE = (22, 128, 68)
_DRIVER_SENTIMENT_NEGATIVE = (196, 58, 58)
_DRIVER_SENTIMENT_NEUTRAL = (100, 116, 139)

# Драйверы, где снижение показателя — позитив для сектора (издержки, топливо и т.п.).
_DRIVER_COST_MARKERS: tuple[str, ...] = (
    "топлив",
    "издерж",
    "затрат",
    "себестоим",
    "фондирован",
    "стоимость капитал",
    "логистик",
    "расход",
)
# Рост предложения / добычи — негатив для производителей сырья.
_DRIVER_SUPPLY_MARKERS: tuple[str, ...] = (
    "предложен",
    "добыч",
    "поставк",
)
# Драйверы, где рост — позитив (спрос, маржа, приток и т.п.).
_DRIVER_GROWTH_POSITIVE_MARKERS: tuple[str, ...] = (
    "спрос",
    "выручк",
    "заказ",
    "загрузк",
    "приток",
    "оценк",
    "производств",
    "марж",
    "ликвидност",
)
# Цена реализуемого сырья / продукта.
_DRIVER_COMMODITY_PRICE_MARKERS: tuple[str, ...] = (
    "цена нефт",
    "цены на нефт",
    "цены на сырь",
)
# Рост этих драйверов — негатив для сектора (убытки, выплаты, резервы).
_DRIVER_NEGATIVE_WHEN_RISING: tuple[str, ...] = (
    "убыт",
    "страхов",
    "выплат",
    "резерв",
    "claims",
    "loss",
    "задерж",
    "простой",
)
# Маркеры влияния новости на котировку (§3).
_COMPANY_NEWS_POSITIVE_MARKERS: tuple[tuple[str, int], ...] = (
    ("восстановлен", 2),
    ("отскок", 2),
    ("повышение прогноз", 2),
    ("повысил прогноз", 2),
    ("повышение", 2),
    ("повысил", 2),
    ("поддержк", 2),
    ("ожидания сильного", 2),
    ("сильн", 1),
    ("рост котиров", 2),
    ("рост на", 1),
    ("улучшен", 2),
    ("одобрен", 2),
    ("рекорд", 2),
    ("превысил", 2),
    ("выигрыш", 2),
    ("бенефициар", 2),
)
_COMPANY_NEWS_NEGATIVE_MARKERS: tuple[tuple[str, int], ...] = (
    ("осторожност", 3),
    ("предупред", 2),
    ("тарифн", 2),
    ("неопределён", 2),
    ("неопределен", 2),
    ("риск", 1),
    ("слаб", 1),
    ("паден", 2),
    ("давлен", 2),
    ("давит", 2),
    ("ухудшен", 2),
    ("убыт", 2),
    ("сокращен", 2),
    ("понижен", 2),
    ("снижен", 1),
    ("коррекци", 1),
    ("санкц", 2),
)

# Множители ширины колонок по заголовку (узкие служебные, широкие текстовые).
_COL_WIDTH_HINTS: tuple[tuple[str, float], ...] = (
    ("приоритет", 0.55),
    ("сила события", 0.42),
    ("сила", 0.38),
    ("влияние", 0.55),
    ("рейтинг", 0.55),
    ("#", 0.28),
    ("время", 0.85),
    ("дата", 0.75),
    ("isin", 0.85),
    ("тикер", 0.7),
    ("важность", 0.65),
    ("кол-во", 0.55),
    ("объём", 0.6),
    ("доля", 0.55),
    ("сектор", 0.9),
    ("компания", 1.0),
    ("зона", 0.55),
    ("значимость", 0.65),
    ("отрасль", 1.0),
    ("событие", 1.25),
    ("драйвер", 1.2),
    ("влияние", 1.3),
    ("реакция", 1.1),
    ("почему", 1.15),
    ("потенциальное", 1.1),
    ("возможное", 1.1),
    ("название", 1.2),
    ("бумага", 1.0),
    ("группа", 0.85),
    ("состав", 1.2),
)


@dataclass
class MdTable:
    headers: list[str]
    rows: list[list[str]]


@dataclass
class MdHeading:
    level: int
    text: str


@dataclass
class MdParagraph:
    text: str
    italic: bool = False


@dataclass
class MdBulletList:
    items: list[str]


@dataclass
class MdHr:
    pass


MdBlock = MdTable | MdHeading | MdParagraph | MdBulletList | MdHr


def _find_fonts() -> tuple[Path, Path, Path | None]:
    for regular, bold, italic in _FONT_TRIPLETS:
        if regular.is_file() and bold.is_file():
            italic_path = italic if italic and italic.is_file() else None
            return regular, bold, italic_path
    raise RuntimeError(
        "Не найден TTF-шрифт с кириллицей. "
        "На Windows нужен Arial (C:\\Windows\\Fonts\\arial.ttf)."
    )


def _find_star_font() -> Path | None:
    for path in _STAR_FONT_PATHS:
        if path.is_file():
            return path
    return None


def _sanitize_for_pdf(text: str) -> str:
    replacements = {
        "🔴": "●",
        "🟡": "●",
        "🟢": "●",
        "⚪": "●",
        "—": "-",
        "–": "-",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return _EMOJI_RE.sub("", text)


def _is_report_boilerplate(text: str) -> bool:
    normalized = text.strip().strip("_").strip()
    return any(normalized.startswith(prefix) for prefix in _REPORT_BOILERPLATE_PREFIXES)


def _parse_table_row(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [cell.strip() for cell in inner.split("|")]


def _is_table_separator(line: str) -> bool:
    return bool(_TABLE_SEP_RE.match(line.strip()))


def _parse_table(lines: list[str]) -> MdTable | None:
    if not lines:
        return None
    headers = _parse_table_row(lines[0])
    if not headers:
        return None
    data_start = 1
    if len(lines) > 1 and _is_table_separator(lines[1]):
        data_start = 2
    ncol = len(headers)
    rows: list[list[str]] = []
    for line in lines[data_start:]:
        row = _parse_table_row(line)
        if len(row) < ncol:
            row.extend([""] * (ncol - len(row)))
        elif len(row) > ncol:
            row = row[:ncol]
        rows.append(row)
    return MdTable(headers=headers, rows=rows)


def _iter_markdown_blocks(text: str) -> Iterator[MdBlock]:
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped:
            i += 1
            continue

        if stripped == "---":
            yield MdHr()
            i += 1
            continue

        if stripped.startswith("#"):
            level = 0
            while level < len(stripped) and stripped[level] == "#":
                level += 1
            heading_text = stripped[level:].strip()
            if heading_text.lower() in _AI_SECTION_MARKERS:
                i += 1
                continue
            yield MdHeading(level=level, text=heading_text)
            i += 1
            continue

        if stripped.startswith("|") and stripped.count("|") >= 2:
            table_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            table = _parse_table(table_lines)
            if table:
                yield table
            continue

        if stripped.startswith("- "):
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            yield MdBulletList(items=items)
            continue

        para_lines: list[str] = []
        while i < len(lines):
            s = lines[i].strip()
            if not s or s == "---" or s.startswith("#") or (
                s.startswith("|") and s.count("|") >= 2
            ) or s.startswith("- "):
                break
            para_lines.append(s)
            i += 1
        joined = " ".join(para_lines)
        italic = joined.startswith("_") and joined.endswith("_") and joined.count("_") >= 2
        if italic:
            joined = joined.strip("_").strip()
        if _is_report_boilerplate(joined):
            continue
        yield MdParagraph(text=joined, italic=italic)


def _width_hint(header: str) -> float:
    h = header.lower().strip()
    if h in {"влияние", "значимость"}:
        return 0.65
    for key, mult in _COL_WIDTH_HINTS:
        if key in h or h == key:
            return mult
    return 1.0


def _looks_numeric(value: str) -> bool:
    v = value.strip()
    if not v or v in {"-", "—"}:
        return False
    return bool(_NUMERIC_RE.match(v))


def _is_index_header(header: str) -> bool:
    return header.strip().lower() in _INDEX_HEADERS


def _is_impact_score_header(header: str) -> bool:
    """Числовая колонка «Влияние» / «Сила» (−5…+5), не текстовый драйвер."""
    h = header.strip().lower()
    if h in {"влияние", "значимость", "рейтинг", "сила", "важность"}:
        return True
    if h == "сила события":
        return True
    return False


def _is_sector_rating_header(header: str) -> bool:
    """Колонка «Влияние» / «Рейтинг» в §2."""
    return _is_impact_score_header(header)


def _is_portfolio_influence_header(header: str) -> bool:
    """Колонка «Влияние» в §3."""
    h = header.strip().lower()
    return h in {"влияние", "значимость"}


def _column_align(header: str, values: list[str]) -> str:
    h = header.lower().strip()
    if _is_index_header(header) or _is_impact_score_header(header):
        return "CENTER"
    if h == "время":
        return "CENTER"
    if "важность" in h and not _is_impact_score_header(header):
        return "CENTER"
    if any(k in h for k in ("кол-во", "количество")):
        return "CENTER"
    if "стоимость" in h:
        return "CENTER"
    if "доля %" in h or h == "доля":
        return "CENTER"
    if "объём" in h:
        return "RIGHT"
    if h in {"#", "приоритет", "isin", "тикер"} or h.startswith("дата"):
        return "CENTER"
    if "дата" in h:
        return "CENTER"
    non_empty = [v for v in values if v.strip() and v.strip() not in {"-", "—"}]
    if non_empty and all(_looks_numeric(v) for v in non_empty):
        return "RIGHT"
    return "LEFT"


def _match_column_fractions(headers: list[str]) -> tuple[float, ...] | None:
    """Профили ширин для типовых таблиц отчёта."""
    n = len(headers)
    h = [x.lower().strip() for x in headers]

    if n == 3:
        if "приоритет" in h[0] and "влияние" in h[2]:
            return (0.14, 0.40, 0.46)
        if "isin" in h[0] and "кол-во" in h[2]:
            return (0.18, 0.62, 0.20)
        if h[0] == "#" and "тикер" in h[2]:
            return (0.06, 0.64, 0.30)
        if "отрасль" in h[0] and "isin" in h[1]:
            return (0.34, 0.18, 0.48)
        if "отрасль" in h[0] and "драйвер" in h[1]:
            return (0.18, 0.46, 0.36)

    if n == 4:
        if h[0] in {"#", "№"} and "отрасль" in h[1] and h[2] in {"рейтинг", "влияние"}:
            return (0.05, 0.35, 0.10, 0.50)
        if "событие" in h[0] and h[1] in {"сила события", "влияние"}:
            return _TABLE1_COL_WIDTHS
        if h[0] == "#" and "отрасль" in h[3]:
            return (0.05, 0.40, 0.20, 0.35)

    if n == 5:
        if h[0] == "#" and "событие" in h[1] and h[2] in {"сила", "влияние", "сила события"}:
            return _TABLE1_COL_WIDTHS
        if "isin" in h[0] and "название" in h[1] and "кол-во" in h[2] and "стоимость" in h[3]:
            # ISIN +30% за счёт «Кол-во», «Стоимость EUR», «Доля %»
            return (0.19, 0.40, 0.13, 0.14, 0.14)
        if h[0] == "#" and "отрасль" in h[4] and any("доля" in col for col in h):
            return (0.05, 0.32, 0.14, 0.14, 0.35)
        if "дата" in h[0] and "важность" in h[2] and "потенциальное" in h[4]:
            return (0.11, 0.22, 0.132, 0.26, 0.278)
        if "дата" in h[0] and "сектор" in h[2]:
            return (0.12, 0.13, 0.15, 0.32, 0.28)
        if "дата" in h[0] and "почему важно" in h[3]:
            return (0.13, 0.17, 0.16, 0.28, 0.26)
        if h[0] == "время" and h[1] == "событие" and h[2] == "тип" and h[3] in {"важность", "влияние"}:
            return _TABLE4_COL_WIDTHS
        if "компания" in h[0] and "зона" in h[1] and "новость" in h[3]:
            return _TABLE3_COL_WIDTHS

    return None


def _fixed_table_col_widths(headers: list[str]) -> tuple[float, ...] | None:
    """Жёсткие профили ширин для таблиц §1–§4 (приоритет над _match_column_fractions)."""
    if _is_top_market_news_table(headers):
        return _TABLE1_COL_WIDTHS
    if _is_portfolio_companies_news_table(headers):
        return _TABLE3_COL_WIDTHS
    h = [x.lower().strip() for x in headers]
    if len(headers) == 5 and h[0] == "#" and "событие" in h[1]:
        return _TABLE1_COL_WIDTHS
    if len(headers) == 4 and h[0] in {"#", "№"} and "отрасль" in h[1] and h[2] in {"рейтинг", "влияние"}:
        return _TABLE2_COL_WIDTHS
    if (
        len(headers) == 5
        and h[0] == "время"
        and h[1] == "событие"
        and h[2] == "тип"
        and h[3] in {"важность", "влияние"}
    ):
        return _TABLE4_COL_WIDTHS
    return None


def _col_width_percents(col_widths: tuple[float, ...]) -> tuple[float, ...]:
    total = sum(col_widths)
    if total <= 0:
        return col_widths
    return tuple(100.0 * w / total for w in col_widths)


def _is_top_market_news_table(headers: list[str]) -> bool:
    """§1 — топ новости: # | Событие | Сила | Сектор | Драйвер."""
    if len(headers) == 5:
        h = [x.lower().strip() for x in headers]
        return (
            h[0] == "#"
            and "событие" in h[1]
            and h[2] in {"сила", "влияние", "сила события"}
            and "сектор" in h[3]
            and "драйвер" in h[4]
        )
    if len(headers) != 4:
        return False
    h = [x.lower().strip() for x in headers]
    impact_col = h[1] in {"сила события", "влияние", "сила"}
    driver_col = "драйвер" in h[3] or ("влияние" in h[3] and "драйвер" in h[3])
    return "событие" in h[0] and impact_col and "сектор" in h[2] and driver_col


def _top_news_event_col_index(headers: list[str]) -> int:
    h = [x.lower().strip() for x in headers]
    if h and h[0] == "#":
        return 1
    return 0


def _top_news_impact_col_index(headers: list[str]) -> int | None:
    h = [x.lower().strip() for x in headers]
    if len(h) >= 5 and h[0] == "#":
        return 2
    if len(h) >= 4:
        if h[1] in {"сила", "влияние", "сила события"}:
            return 1
    return None


def _top_news_merge_col_indices(headers: list[str]) -> tuple[int, ...]:
    if len(headers) == 5 and headers[0].strip() == "#":
        return (0, 1, 2)
    return (0, 1)


def _sort_top_market_news_rows(headers: list[str], rows: list[list[str]]) -> list[list[str]]:
    """§1: сортировка по |влияние| (убывание), перенумерация #."""
    if not rows:
        return rows
    impact_col = _top_news_impact_col_index(headers)
    if impact_col is None:
        return rows
    event_col = _top_news_event_col_index(headers)
    index_col = 0 if headers and _is_index_header(headers[0]) else None

    def group_sort_key(start_span: tuple[int, int]) -> tuple[int, int]:
        start, _span = start_span
        cell = rows[start][impact_col] if impact_col < len(rows[start]) else ""
        score = parse_impact_score(cell)
        abs_score = abs(score) if score is not None else -1
        return (-abs_score, start)

    groups = _top_news_event_groups(rows, event_col=event_col)
    sorted_groups = sorted(groups, key=group_sort_key)

    sorted_rows: list[list[str]] = []
    num = 1
    for start, span in sorted_groups:
        for offset in range(span):
            row = list(rows[start + offset])
            if index_col is not None and index_col < len(row):
                row[index_col] = str(num)
            sorted_rows.append(row)
        num += 1
    return sorted_rows


def _prepare_top_market_news_table(table: MdTable) -> MdTable:
    if not _is_top_market_news_table(table.headers):
        return table
    return MdTable(
        headers=table.headers,
        rows=_sort_top_market_news_rows(table.headers, table.rows),
    )


def _is_portfolio_companies_news_table(headers: list[str]) -> bool:
    """§3 — новости по компаниям портфеля и watchlist."""
    if len(headers) != 5:
        return False
    h = [x.lower().strip() for x in headers]
    return (
        "компания" in h[0]
        and "зона" in h[1]
        and "новость" in h[3]
        and ("влияние" in h[4] or "значимость" in h[4])
    )


def _top_news_event_groups(
    rows: list[list[str]],
    *,
    event_col: int,
) -> list[tuple[int, int]]:
    """Группы подряд идущих строк с одинаковым событием: (индекс первой, rowspan)."""
    if not rows:
        return []
    groups: list[tuple[int, int]] = []
    start = 0
    current = _normalize_text(rows[0][event_col] if rows[0] and event_col < len(rows[0]) else "")
    for i in range(1, len(rows)):
        event = _normalize_text(rows[i][event_col] if event_col < len(rows[i]) else "")
        if event != current:
            groups.append((start, i - start))
            start = i
            current = event
    groups.append((start, len(rows) - start))
    return groups


def _table_impact_col_index(headers: list[str]) -> int | None:
    """Индекс числовой колонки «Влияние» / «Сила» в таблице отчёта."""
    for j, header in enumerate(headers):
        if _is_impact_score_header(header):
            return j
    return None


def _table_row_sentiments(
    headers: list[str],
    rows: list[list[str]],
    *,
    merge_top_news: bool = False,
    event_col: int = 0,
) -> list[str | None]:
    """Позитив / негатив / нейтраль для каждой строки по колонке «Влияние»."""
    impact_col = _table_impact_col_index(headers)
    if impact_col is None:
        return [None] * len(rows)

    if merge_top_news:
        return [
            _top_news_event_sentiment(headers, rows, row_index, event_col=event_col)
            for row_index in range(len(rows))
        ]

    sentiments: list[str | None] = []
    for row in rows:
        val = row[impact_col] if impact_col < len(row) else ""
        sentiments.append(impact_sentiment(val))
    return sentiments


def _top_news_driver_col_index(headers: list[str]) -> int | None:
    for j, header in enumerate(headers):
        if "драйвер" in header.lower():
            return j
    return None


def _top_news_sector_col_index(headers: list[str]) -> int | None:
    for j, header in enumerate(headers):
        if "сектор" in header.lower():
            return j
    return None


def _top_news_event_sentiment(
    headers: list[str],
    rows: list[list[str]],
    row_index: int,
    *,
    event_col: int,
) -> str | None:
    """Сентимент события по колонке «Сила» (для объединённых ячеек # / Событие / Сила)."""
    impact_col = _top_news_impact_col_index(headers)
    if impact_col is None:
        return None
    for start, span in _top_news_event_groups(rows, event_col=event_col):
        if start <= row_index < start + span:
            val = rows[start][impact_col] if impact_col < len(rows[start]) else ""
            return impact_sentiment(val)
    return None


def _top_news_cell_sentiment(
    headers: list[str],
    row: list[str],
    col_index: int,
    event_sentiment: str | None,
) -> str | None:
    """§1: сектор и драйвер — по вектору давления на отрасль; # / Событие / Сила — по событию."""
    merge_cols = set(_top_news_merge_col_indices(headers))
    if col_index in merge_cols:
        return event_sentiment

    driver_col = _top_news_driver_col_index(headers)
    sector_col = _top_news_sector_col_index(headers)
    if driver_col is None or col_index not in {driver_col, sector_col}:
        return event_sentiment

    driver_text = row[driver_col] if driver_col < len(row) else ""
    return _driver_influence_sentiment(driver_text) or "neutral"


def _sentiment_text_color(sentiment: str | None) -> tuple[int, int, int]:
    if sentiment:
        return _driver_sentiment_color(sentiment)
    return _TABLE_BODY_TEXT_COLOR


def _row_cell_style(
    sentiment: str | None,
    *,
    font_size: float,
) -> FontFace:
    return FontFace(
        family=FONT_REGULAR,
        size_pt=font_size,
        color=_sentiment_text_color(sentiment),
        fill_color=_TABLE_BODY_ROW_FILL,
    )


def _driver_change_direction(change: str) -> tuple[bool, bool]:
    """Направление изменения драйвера: (рост, снижение)."""
    is_rise = any(
        marker in change
        for marker in (
            "рост",
            "повыш",
            "выше",
            "вверх",
            "расшир",
            "увелич",
            "нараст",
        )
    )
    is_fall = any(
        marker in change
        for marker in (
            "снижен",
            "сниж",
            "паден",
            "ниже",
            "ниж",
            "вниз",
            "сокращ",
            "уменьш",
            "сжат",
        )
    )
    if "давлен" in change and "вниз" in change:
        is_fall = True
    return is_rise, is_fall


def _driver_cost_context(driver: str, change: str) -> bool:
    return any(marker in driver for marker in _DRIVER_COST_MARKERS) or any(
        marker in change for marker in ("издерж", "затрат", "расход")
    )


def _driver_clause_sentiment(clause: str) -> str | None:
    """Позитив / негатив / нейтраль для одного драйвера «{драйвер}: {изменение}»."""
    text = _normalize_text(clause).lower()
    if not text:
        return None

    if ":" in text:
        driver, change = text.rsplit(":", 1)
        driver = driver.strip()
        change = change.strip()
    else:
        driver, change = text, ""

    if "стабильн" in change:
        return "neutral"
    if "неопредел" in change:
        return "negative"
    if "расширение марж" in change:
        return "positive"
    if "сжатие марж" in change:
        return "negative"
    is_rise, is_fall = _driver_change_direction(change)
    if is_fall and ("поддерживает спрос" in change or "поддержка спрос" in change):
        return "positive"
    if not is_rise and not is_fall:
        return None

    if any(marker in driver for marker in _DRIVER_NEGATIVE_WHEN_RISING):
        return "negative" if is_rise else "positive"
    if _driver_cost_context(driver, change):
        return "positive" if is_fall else "negative"
    if any(marker in driver for marker in _DRIVER_SUPPLY_MARKERS):
        return "negative" if is_rise else "positive"
    if "доходность альтернатив" in driver:
        return "negative" if is_rise else "positive"
    if "риск" in driver or "тариф" in driver:
        return "negative" if is_rise else "positive"
    if any(marker in driver for marker in _DRIVER_COMMODITY_PRICE_MARKERS):
        return "positive" if is_rise else "negative"
    if "конкурентоспособност" in driver:
        return "positive" if is_rise else "negative"
    if any(marker in driver for marker in _DRIVER_GROWTH_POSITIVE_MARKERS):
        return "positive" if is_rise else "negative"

    return "positive" if is_rise else "negative"


def _driver_influence_sentiment(influence: str) -> str | None:
    """Позитив / негатив / нейтраль по вектору давления на отрасль (драйвер сектора)."""
    text = _normalize_text(influence).lower()
    if not text:
        return None

    clauses = [part.strip() for part in text.split(";") if part.strip()]
    if len(clauses) <= 1:
        return _driver_clause_sentiment(text)

    sentiments = [_driver_clause_sentiment(clause) for clause in clauses]
    sentiments = [s for s in sentiments if s]
    if not sentiments:
        return None
    if all(s == sentiments[0] for s in sentiments):
        return sentiments[0]
    if "negative" in sentiments:
        return "negative"
    if "positive" in sentiments:
        return "positive"
    return "neutral"


def _company_news_price_impact_sentiment(news: str) -> str | None:
    """Позитив / негатив / нейтраль для влияния новости на стоимость бумаги (§3)."""
    text = _normalize_text(news).lower()
    if not text or text in {"—", "-", "н/д", "n/a"}:
        return None
    if "не выявлено" in text or "значимых новостей" in text:
        return None

    if any(marker in text for marker in ("стабильн", "без изменений", "смешанн", "боковик")):
        return "neutral"

    pos = sum(weight for marker, weight in _COMPANY_NEWS_POSITIVE_MARKERS if marker in text)
    neg = sum(weight for marker, weight in _COMPANY_NEWS_NEGATIVE_MARKERS if marker in text)

    if any(marker in text for marker in ("восстановлен", "отскок", "поддержк")):
        neg = max(0, neg - 1)
    if "поддержк" in text and any(marker in text for marker in ("нефт", "топлив")):
        neg = max(0, neg - 1)
    if "рост" in text and any(
        marker in text for marker in ("риск", "осторожност", "неопредел")
    ):
        pos = max(0, pos - 1)
        neg += 1
    if "рост" in text and "рост котиров" not in text and "рост на" not in text:
        pos += 1

    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return None


def _driver_sentiment_color(sentiment: str) -> tuple[int, int, int]:
    return {
        "positive": _DRIVER_SENTIMENT_POSITIVE,
        "negative": _DRIVER_SENTIMENT_NEGATIVE,
        "neutral": _DRIVER_SENTIMENT_NEUTRAL,
    }[sentiment]


def _compute_col_widths(
    pdf: FPDF,
    headers: list[str],
    rows: list[list[str]],
    *,
    font_size: float,
) -> tuple[float, ...]:
    preset = _match_column_fractions(headers)
    if preset:
        return preset

    pdf.set_font(FONT_REGULAR, size=font_size)
    n = len(headers)
    even_mm = pdf.epw / n
    sample_cap = min(even_mm * 2.2, pdf.epw * 0.34)

    weights: list[float] = []
    for j, header in enumerate(headers):
        samples = [header]
        for row in rows:
            if j < len(row) and row[j]:
                samples.append(row[j])
        widths = sorted(
            min(pdf.get_string_width(sample) + 3.0, sample_cap) for sample in samples
        )
        idx = min(len(widths) - 1, max(0, len(widths) * 2 // 3))
        base = widths[idx]
        hint = max(_width_hint(header), 0.75)
        weights.append(max(base * hint, even_mm * 0.55))

    min_frac = max(0.08, 0.55 / n)
    fractions = [w / sum(weights) for w in weights]
    fractions = [max(f, min_frac) for f in fractions]
    total = sum(fractions)
    return tuple(f / total for f in fractions)


def _table_font_size(ncols: int) -> float:
    if ncols >= 5:
        return 7.5
    if ncols == 4:
        return 8.0
    return 8.5


def _table_header_font_size(body_size: float) -> float:
    return body_size + _TABLE_HEADER_SIZE_BOOST


def _header_cell_text(text: str) -> str:
    """Заголовок колонки: короткие подписи без разрыва слов."""
    normalized = " ".join(text.strip().split())
    short = {
        "Сила события": "Сила",
        "Влияние на драйвер сектора": "Драйвер",
    }
    return short.get(normalized, normalized)


def _normalize_heading_text(text: str) -> str:
    """Убирает шкалу (−5…+5) из заголовков секций в PDF."""
    normalized = _normalize_text(text)
    return _HEADING_SCALE_SUFFIX_RE.sub("", normalized).rstrip()


def _normalize_text(text: str) -> str:
    """Обычные пробелы — перенос строк в PDF только между словами (WrapMode.WORD)."""
    return " ".join(text.strip().split())


def _column_kind(header: str) -> str | None:
    h = header.lower().strip()
    if _is_index_header(header):
        return "index"
    if _is_impact_score_header(header):
        return "impact_score"
    if h == "приоритет" or h.startswith("приоритет"):
        return "priority"
    if h == "время":
        return "time"
    if "отрасль" in h:
        return "sector"
    return None


def _format_importance_stars(value: str) -> str:
    """Нормализует оценку важности в ★★★★☆ (закрашенные / пустые звёзды)."""
    text = value.strip()
    if not text:
        return text
    if re.fullmatch(r"[★☆]+", text):
        count = text.count("★")
    elif re.fullmatch(r"[*\-]+", text):
        count = text.count("*")
    else:
        digit = re.search(r"(\d)\s*/\s*5", text)
        if digit:
            count = int(digit.group(1))
        else:
            count = text.count("★") + text.count("*")
            if count == 0:
                return text
    count = max(0, min(5, count))
    return _STAR_FILLED * count + _STAR_EMPTY * (5 - count)


def _format_table_cell(header: str, value: str) -> str:
    kind = _column_kind(header)
    if kind == "impact_score":
        if parse_impact_score(value) is not None:
            return format_impact_score(value)
        return _format_importance_stars(value)
    if kind in {"priority", "index", "time"}:
        return value.strip()
    return _normalize_text(value)


def _ensure_header_fits(
    pdf: FPDF,
    headers: list[str],
    col_widths: tuple[float, ...],
    *,
    header_font_size: float,
) -> tuple[float, ...]:
    """Расширяет колонку, если заголовок не помещается в одну строку."""
    pdf.set_font(FONT_REGULAR, "B", header_font_size)
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    padding = 3.2
    adjusted = list(widths_mm)
    for j, header in enumerate(headers):
        kind = _column_kind(header)
        if kind in {"impact_score", "portfolio_influence"}:
            continue
        label = _header_cell_text(header)
        needed = pdf.get_string_width(label) + padding
        if needed > adjusted[j]:
            adjusted[j] = needed
    total = sum(adjusted)
    if total <= epw:
        return tuple(w / epw for w in adjusted)
    scale = epw / total
    return tuple((w * scale) / epw for w in adjusted)


def _ensure_importance_col_width(
    pdf: FPDF,
    headers: list[str],
    col_widths: tuple[float, ...],
    *,
    font_size: float,
) -> tuple[float, ...]:
    """Колонка «Важность»: достаточно места для пяти звёзд по центру."""
    star_label = _format_importance_stars("★★★★★")
    pdf.set_font(FONT_REGULAR, size=font_size)
    needed_mm = pdf.get_string_width(star_label) + 4.0
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    for j, header in enumerate(headers):
        if _column_kind(header) != "importance":
            continue
        if needed_mm > widths_mm[j]:
            widths_mm[j] = needed_mm
    total = sum(widths_mm)
    if total <= epw:
        return tuple(w / epw for w in widths_mm)
    scale = epw / total
    return tuple((w * scale) / epw for w in widths_mm)


def _ensure_priority_col_width(
    pdf: FPDF,
    headers: list[str],
    col_widths: tuple[float, ...],
    *,
    header_font_size: float,
) -> tuple[float, ...]:
    """Колонка «Приоритет»: заголовок и ранг помещаются без разрыва слова."""
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    padding = 4.0
    changed = False
    for j, header in enumerate(headers):
        if _column_kind(header) != "priority":
            continue
        pdf.set_font(FONT_REGULAR, "B", header_font_size)
        needed = pdf.get_string_width(_header_cell_text(header)) + padding
        if needed > widths_mm[j]:
            widths_mm[j] = needed
            changed = True
    if not changed:
        return col_widths
    total = sum(widths_mm)
    if total <= epw:
        return tuple(w / epw for w in widths_mm)
    scale = epw / total
    return tuple((w * scale) / epw for w in widths_mm)


def _ensure_index_col_width(
    pdf: FPDF,
    headers: list[str],
    col_widths: tuple[float, ...],
    *,
    header_font_size: float,
    font_size: float,
) -> tuple[float, ...]:
    """Колонка «№» / «#»: минимальная ширина под порядковый номер."""
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    padding = 3.0
    changed = False
    for j, header in enumerate(headers):
        if _column_kind(header) != "index":
            continue
        pdf.set_font(FONT_REGULAR, "B", header_font_size)
        needed = max(
            pdf.get_string_width(_header_cell_text(header)) + padding,
            pdf.get_string_width("№") + padding,
        )
        pdf.set_font(FONT_REGULAR, size=font_size)
        needed = max(needed, pdf.get_string_width("99") + padding)
        if needed > widths_mm[j]:
            widths_mm[j] = needed
            changed = True
    if not changed:
        return col_widths
    total = sum(widths_mm)
    if total <= epw:
        return tuple(w / epw for w in widths_mm)
    scale = epw / total
    return tuple((w * scale) / epw for w in widths_mm)


def _ensure_event_strength_col_width(
    pdf: FPDF,
    headers: list[str],
    col_widths: tuple[float, ...],
    *,
    header_font_size: float,
    font_size: float,
) -> tuple[float, ...]:
    """Колонка «Сила события»: узкая, значение 1–5 по центру; заголовок переносится."""
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    padding = 3.5
    changed = False
    for j, header in enumerate(headers):
        if _column_kind(header) != "impact_score":
            continue
        pdf.set_font(FONT_REGULAR, size=font_size)
        needed = max(
            pdf.get_string_width("+5") + padding,
            pdf.get_string_width("−5") + padding,
        )
        if needed > widths_mm[j]:
            widths_mm[j] = needed
            changed = True
    if not changed:
        return col_widths
    total = sum(widths_mm)
    if total <= epw:
        return tuple(w / epw for w in widths_mm)
    scale = epw / total
    return tuple((w * scale) / epw for w in widths_mm)


def _ensure_time_col_width(
    pdf: FPDF,
    headers: list[str],
    col_widths: tuple[float, ...],
    *,
    header_font_size: float,
    font_size: float,
) -> tuple[float, ...]:
    """Колонка «Время» (§4): узкая, без переноса «11:00» / «После закрытия US»."""
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    padding = 3.5
    changed = False
    for j, header in enumerate(headers):
        if _column_kind(header) != "time":
            continue
        pdf.set_font(FONT_REGULAR, "B", header_font_size)
        needed = pdf.get_string_width(_header_cell_text(header)) + padding
        pdf.set_font(FONT_REGULAR, size=font_size)
        for sample in ("11:00", "После закрытия US"):
            needed = max(needed, pdf.get_string_width(sample) + padding)
        if needed > widths_mm[j]:
            widths_mm[j] = needed
            changed = True
    if not changed:
        return col_widths
    total = sum(widths_mm)
    if total <= epw:
        return tuple(w / epw for w in widths_mm)
    scale = epw / total
    return tuple((w * scale) / epw for w in widths_mm)


def _ensure_top_news_impact_col_width(
    pdf: FPDF,
    headers: list[str],
    col_widths: tuple[float, ...],
    *,
    header_font_size: float,
) -> tuple[float, ...]:
    """§1: заголовок «Влияние» в одну строку — за счёт колонки «Драйвер сектора»."""
    if not _is_top_market_news_table(headers):
        return col_widths
    impact_j = _top_news_impact_col_index(headers)
    if impact_j is None:
        return col_widths
    driver_j = len(headers) - 1
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    padding = 4.0
    pdf.set_font(FONT_REGULAR, "B", header_font_size)
    needed = pdf.get_string_width(_header_cell_text(headers[impact_j])) + padding
    if needed <= widths_mm[impact_j]:
        return col_widths
    delta = needed - widths_mm[impact_j]
    min_driver = max(widths_mm[driver_j] * 0.45, epw * 0.18)
    if widths_mm[driver_j] - delta < min_driver:
        delta = max(0.0, widths_mm[driver_j] - min_driver)
    if delta <= 0:
        return col_widths
    widths_mm[impact_j] += delta
    widths_mm[driver_j] -= delta
    return tuple(w / epw for w in widths_mm)


def _reference_impact_col_fraction(
    pdf: FPDF,
    *,
    font_size: float | None = None,
    header_font_size: float | None = None,
) -> float:
    """Доля epw для колонки «Влияние» по эталону таблицы §1."""
    body_size = font_size if font_size is not None else _table_font_size(5)
    header_size = (
        header_font_size
        if header_font_size is not None
        else _table_header_font_size(body_size)
    )
    headers = list(_REF_TABLE_HEADERS)
    col_widths = _TABLE1_COL_WIDTHS
    col_widths = _ensure_top_news_impact_col_width(
        pdf,
        headers,
        col_widths,
        header_font_size=header_size,
    )
    col_widths = _ensure_sector_rating_col_width(
        pdf,
        headers,
        col_widths,
        header_font_size=header_size,
        font_size=body_size,
    )
    impact_j = _table_impact_col_index(headers)
    assert impact_j is not None
    return col_widths[impact_j]


def _apply_reference_impact_col_width(
    pdf: FPDF,
    headers: list[str],
    col_widths: tuple[float, ...],
    reference_fraction: float,
) -> tuple[float, ...]:
    """Выравнивает колонку «Влияние» по эталону §1, перераспределяя ширину остальных."""
    impact_j = _table_impact_col_index(headers)
    if impact_j is None:
        return col_widths
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    target_mm = reference_fraction * epw
    delta = target_mm - widths_mm[impact_j]
    if abs(delta) < 0.05:
        return col_widths
    widths_mm[impact_j] = target_mm
    others = [i for i in range(len(headers)) if i != impact_j]
    other_total = sum(widths_mm[i] for i in others)
    if other_total <= 0:
        return col_widths
    for i in others:
        widths_mm[i] -= delta * (widths_mm[i] / other_total)
    min_mm = epw * 0.04
    for i in others:
        if widths_mm[i] < min_mm:
            widths_mm[i] = min_mm
    total = sum(widths_mm)
    if total > epw:
        scale = epw / total
        widths_mm = [w * scale for w in widths_mm]
    return tuple(w / epw for w in widths_mm)


def _ensure_sector_rating_col_width(
    pdf: FPDF,
    headers: list[str],
    col_widths: tuple[float, ...],
    *,
    header_font_size: float,
    font_size: float,
) -> tuple[float, ...]:
    """Колонка «Влияние» (−5…+5): узкая, значения по центру без переноса."""
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    padding = 5.0
    changed = False
    for j, header in enumerate(headers):
        if _column_kind(header) != "impact_score":
            continue
        pdf.set_font(FONT_REGULAR, "B", header_font_size)
        needed = pdf.get_string_width(_header_cell_text(header)) + padding
        pdf.set_font(FONT_REGULAR, size=font_size)
        for sample in ("+5", "−5", "-5", "Рейтинг"):
            needed = max(needed, pdf.get_string_width(sample) + padding)
        if needed > widths_mm[j]:
            widths_mm[j] = needed
            changed = True
    if not changed:
        return col_widths
    total = sum(widths_mm)
    if total <= epw:
        return tuple(w / epw for w in widths_mm)
    scale = epw / total
    return tuple((w * scale) / epw for w in widths_mm)


def _ensure_sector_col_width(
    pdf: FPDF,
    headers: list[str],
    rows: list[list[str]],
    col_widths: tuple[float, ...],
    *,
    font_size: float,
) -> tuple[float, ...]:
    """Колонка «Отрасль»: оценка ширины по самому длинному слову в ячейке."""
    epw = pdf.epw
    widths_mm = [fraction * epw for fraction in col_widths]
    pdf.set_font(FONT_REGULAR, size=font_size)
    changed = False
    for j, header in enumerate(headers):
        if _column_kind(header) != "sector":
            continue
        max_w = pdf.get_string_width(_header_cell_text(header))
        for row in rows:
            if j < len(row) and row[j]:
                label = _normalize_text(row[j])
                max_w = max(max_w, pdf.get_string_width(label))
        needed = max_w + 4.0
        if needed > widths_mm[j]:
            widths_mm[j] = needed
            changed = True
    if not changed:
        return col_widths
    total = sum(widths_mm)
    if total <= epw:
        return tuple(w / epw for w in widths_mm)
    scale = epw / total
    return tuple((w * scale) / epw for w in widths_mm)


class _ReportPDF(FPDF):
    def __init__(self, footer_title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self._footer_title = footer_title
        self.star_font_loaded = False

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(FONT_REGULAR, size=8)
        self.set_text_color(113, 128, 150)
        self.cell(0, 8, f"ETF News Service · {self._footer_title}", align="C")

    def render_heading(self, block: MdHeading) -> None:
        level = min(block.level, 3)
        self.set_x(self.l_margin)
        self.ln(2 if level > 1 else 4)
        self.set_font(FONT_REGULAR, "B", _HEADING_SIZES[level])
        color = _HEADING_COLORS[level]
        self.set_text_color(*color)
        self.multi_cell(
            self.epw, _HEADING_SIZES[level] * 0.45, _normalize_heading_text(block.text)
        )
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def render_paragraph(self, block: MdParagraph) -> None:
        self.set_x(self.l_margin)
        if block.italic:
            self.set_font(FONT_REGULAR, "I", 9)
            self.set_text_color(74, 85, 104)
        else:
            self.set_font(FONT_REGULAR, size=10)
            self.set_text_color(30, 41, 59)
        self.multi_cell(self.epw, 5, _normalize_text(block.text))
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def render_bullets(self, block: MdBulletList) -> None:
        self.set_font(FONT_REGULAR, size=10)
        self.set_text_color(30, 41, 59)
        bullet_w = 5.0
        text_w = self.epw - bullet_w
        for item in block.items:
            self.set_x(self.l_margin)
            self.cell(bullet_w, 5, "•")
            self.multi_cell(text_w, 5, _normalize_text(item))
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def render_hr(self) -> None:
        self.ln(2)
        y = self.get_y()
        self.set_draw_color(203, 213, 225)
        self.set_line_width(0.2)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(4)

    def render_table(self, table: MdTable) -> None:
        if not table.headers:
            return

        table = _prepare_top_market_news_table(table)

        ncols = len(table.headers)
        font_size = _table_font_size(ncols)
        header_font_size = _table_header_font_size(font_size)
        preset = _fixed_table_col_widths(table.headers) or _match_column_fractions(
            table.headers
        )
        if preset:
            col_widths = preset
            logger.debug(
                "Ширины колонок %s: %s",
                table.headers,
                tuple(round(p, 1) for p in _col_width_percents(col_widths)),
            )
            if _is_top_market_news_table(table.headers):
                col_widths = _ensure_top_news_impact_col_width(
                    self,
                    table.headers,
                    col_widths,
                    header_font_size=header_font_size,
                )
            if any(_column_kind(h) == "impact_score" for h in table.headers):
                col_widths = _ensure_sector_rating_col_width(
                    self,
                    table.headers,
                    col_widths,
                    header_font_size=header_font_size,
                    font_size=font_size,
                )
        else:
            col_widths = _compute_col_widths(
                self, table.headers, table.rows, font_size=font_size
            )
            col_widths = _ensure_header_fits(
                self,
                table.headers,
                col_widths,
                header_font_size=header_font_size,
            )
            col_widths = _ensure_priority_col_width(
                self,
                table.headers,
                col_widths,
                header_font_size=header_font_size,
            )
            col_widths = _ensure_index_col_width(
                self,
                table.headers,
                col_widths,
                header_font_size=header_font_size,
                font_size=font_size,
            )
            col_widths = _ensure_sector_rating_col_width(
                self,
                table.headers,
                col_widths,
                header_font_size=header_font_size,
                font_size=font_size,
            )
            col_widths = _ensure_event_strength_col_width(
                self,
                table.headers,
                col_widths,
                header_font_size=header_font_size,
                font_size=font_size,
            )
            col_widths = _ensure_time_col_width(
                self,
                table.headers,
                col_widths,
                header_font_size=header_font_size,
                font_size=font_size,
            )
            col_widths = _ensure_sector_col_width(
                self, table.headers, table.rows, col_widths, font_size=font_size
            )
        if _table_impact_col_index(table.headers) is not None:
            ref_impact = _reference_impact_col_fraction(
                self,
                font_size=_table_font_size(5),
                header_font_size=_table_header_font_size(_table_font_size(5)),
            )
            col_widths = _apply_reference_impact_col_width(
                self,
                table.headers,
                col_widths,
                ref_impact,
            )
        col_values = [
            [row[j] if j < len(row) else "" for row in table.rows]
            for j in range(ncols)
        ]
        text_align = tuple(
            _column_align(table.headers[j], col_values[j]) for j in range(ncols)
        )

        heading_style = FontFace(
            family=FONT_REGULAR,
            emphasis="BOLD",
            color=(15, 61, 92),
            size_pt=header_font_size,
            fill_color=_TABLE_HEADER_FILL,
        )
        self.set_font(FONT_REGULAR, size=font_size)
        self.ln(1)

        with self.table(
            width=self.epw,
            col_widths=col_widths,
            text_align=text_align,
            v_align="TOP",
            line_height=font_size * 0.50,
            headings_style=heading_style,
            first_row_as_headings=True,
            repeat_headings=True,
            borders_layout=TableBordersLayout.ALL,
            cell_fill_mode=TableCellFillMode.NONE,
            wrapmode=WrapMode.WORD,
            padding=(1.4, 1.6, 1.4, 1.6),
            outer_border_width=0.25,
        ) as pdf_table:
            row = pdf_table.row()
            for header in table.headers:
                row.cell(_header_cell_text(header), align="C", v_align="MIDDLE")
            merge_top_news = _is_top_market_news_table(table.headers)
            event_col = _top_news_event_col_index(table.headers) if merge_top_news else 0
            merge_cols = _top_news_merge_col_indices(table.headers) if merge_top_news else ()
            row_sentiments = _table_row_sentiments(
                table.headers,
                table.rows,
                merge_top_news=merge_top_news,
                event_col=event_col,
            )
            rowspan_by_row: dict[int, int] = {}
            skip_row_indices: set[int] = set()
            if merge_top_news:
                for start, span in _top_news_event_groups(
                    table.rows,
                    event_col=event_col,
                ):
                    if span > 1:
                        rowspan_by_row[start] = span
                        skip_row_indices.update(range(start + 1, start + span))

            for i, data_row in enumerate(table.rows):
                row = pdf_table.row()
                event_sentiment = row_sentiments[i] if merge_top_news else None
                default_row_style = _row_cell_style(
                    row_sentiments[i] if not merge_top_news else None,
                    font_size=font_size,
                )
                for j, cell in enumerate(data_row):
                    if merge_top_news and j in merge_cols and i in skip_row_indices:
                        continue
                    header = table.headers[j]
                    text = _format_table_cell(header, cell)
                    align = text_align[j]
                    rowspan = (
                        rowspan_by_row[i]
                        if merge_top_news and j in merge_cols and i in rowspan_by_row
                        else None
                    )
                    v_align = "MIDDLE" if rowspan else "TOP"
                    cell_kwargs: dict = {}
                    if rowspan:
                        cell_kwargs["rowspan"] = rowspan
                    if merge_top_news:
                        cell_sentiment = _top_news_cell_sentiment(
                            table.headers,
                            data_row,
                            j,
                            event_sentiment,
                        )
                        cell_style = _row_cell_style(cell_sentiment, font_size=font_size)
                    else:
                        cell_style = default_row_style
                    row.cell(
                        text,
                        align=align,
                        v_align=v_align,
                        style=cell_style,
                        **cell_kwargs,
                    )

        self.ln(3)
        self.set_x(self.l_margin)

    def _render_block(self, block: MdBlock) -> None:
        if isinstance(block, MdHeading):
            self.render_heading(block)
        elif isinstance(block, MdParagraph):
            self.render_paragraph(block)
        elif isinstance(block, MdBulletList):
            self.render_bullets(block)
        elif isinstance(block, MdHr):
            self.render_hr()
        elif isinstance(block, MdTable):
            self.render_table(block)

    def _needs_page_before_table_group(self, group: list[MdBlock]) -> bool:
        """Перенос страницы, только если заголовок § и начало таблицы не помещаются вместе."""
        prefix = group[:-1]
        with self.offset_rendering() as probe:
            for block in prefix:
                probe._render_block(block)
            break_limit = probe.h - probe.b_margin
            available = break_limit - probe.get_y()
        return available < _MIN_SPACE_FOR_TABLE_START_MM

    def render_blocks(self, blocks: list[MdBlock]) -> None:
        for group in _section_table_groups(blocks):
            keep_with_table = (
                len(group) > 1 and isinstance(group[-1], MdTable)
            )
            if keep_with_table and self._needs_page_before_table_group(group):
                self.add_page()
            for block in group:
                self._render_block(block)


_MIN_SPACE_FOR_TABLE_START_MM = 20.0


def _section_table_groups(blocks: list[MdBlock]) -> list[list[MdBlock]]:
    """Заголовок §/под§ + вводный текст + таблица — один блок для переноса страницы."""
    groups: list[list[MdBlock]] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if isinstance(block, MdHeading) and block.level >= 2:
            j = i + 1
            intros: list[MdBlock] = []
            while j < len(blocks) and isinstance(blocks[j], MdParagraph):
                intros.append(blocks[j])
                j += 1
            if j < len(blocks) and isinstance(blocks[j], MdTable):
                groups.append([block, *intros, blocks[j]])
                i = j + 1
                continue
        groups.append([block])
        i += 1
    return groups


def export_markdown_to_pdf(
    markdown_text: str,
    output_path: Path | str,
    *,
    title: str = "Еженедельный отчёт биржевой аналитики",
) -> Path:
    """Сохраняет markdown-отчёт в PDF. Возвращает путь к файлу."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    regular, bold, italic = _find_fonts()
    pdf = _ReportPDF(footer_title=title)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(14, 16, 14)
    pdf.add_font(FONT_REGULAR, "", str(regular))
    pdf.add_font(FONT_REGULAR, "B", str(bold))
    pdf.add_font(FONT_REGULAR, "I", str(italic or regular))
    pdf.add_font(FONT_REGULAR, "BI", str(bold))
    star_font = _find_star_font()
    if star_font:
        pdf.add_font(FONT_STARS, "", str(star_font))
        pdf.star_font_loaded = True
    else:
        logger.warning("Шрифт для звёзд важности не найден — используется основной шрифт")

    blocks = list(_iter_markdown_blocks(_sanitize_for_pdf(markdown_text)))

    pdf.add_page()
    pdf.render_blocks(blocks)
    pdf.output(str(output))

    logger.info("PDF сохранён: %s", output.resolve())
    return output.resolve()


def export_report_file_to_pdf(
    markdown_path: Path | str,
    output_path: Path | str | None = None,
    *,
    title: str | None = None,
) -> Path:
    """Конвертирует готовый .md-файл отчёта в PDF."""
    md_path = Path(markdown_path)
    if not md_path.is_file():
        raise FileNotFoundError(f"Файл отчёта не найден: {md_path}")

    text = md_path.read_text(encoding="utf-8")
    if title is None:
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = match.group(1).strip() if match else "Еженедельный отчёт биржевой аналитики"

    out = output_path or md_path.with_suffix(".pdf")
    return export_markdown_to_pdf(text, out, title=title)
