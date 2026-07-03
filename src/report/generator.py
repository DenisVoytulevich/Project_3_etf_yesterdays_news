import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Template
from openai import OpenAI

from src.companies.context import format_companies_for_prompt
from src.config import Settings, get_project_root, load_yaml_config
from src.data.models import PortfolioAnalytics
from src.news.aggregator import format_news_for_prompt
from src.news.models import NewsItem
from src.report.storage import ReportMetadata, ReportResult
from src.sectors.interest import (
    collect_screening_sectors,
    format_interest_sectors_for_prompt,
)
from src.structure.labels import sector_matches
from src.structure.aggregation import StructureAnalysis

logger = logging.getLogger(__name__)

AI_SECTION_KEYS = (
    "executive_summary",
    "top_market_news",
    "sector_ratings",
    "portfolio_companies_news",
    "key_risks_today",
)

_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


class ReportGenerationError(RuntimeError):
    """Отчёт не сформирован: нет успешного ответа OpenAI."""


def _require_openai(settings: Settings) -> None:
    if not (settings.openai_api_key or "").strip():
        raise ReportGenerationError("OPENAI_API_KEY не задан — отчёт не формируется")


def _validate_ai_sections(sections: dict[str, str], keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if not (sections.get(key) or "").strip()]
    if missing:
        raise ReportGenerationError(
            "OpenAI вернул пустые секции: " + ", ".join(missing)
        )


def _load_template(name: str) -> str:
    path = get_project_root() / "templates" / name
    return path.read_text(encoding="utf-8")


def _format_russian_date(dt: datetime) -> str:
    return f"{dt.day} {_MONTHS_GENITIVE[dt.month - 1]} {dt.year}"


def _briefing_dates(now: datetime, tz_name: str) -> tuple[datetime, str, str, str]:
    local = now.astimezone(ZoneInfo(tz_name))
    yesterday = local - timedelta(days=1)
    trading_date = _format_russian_date(local)
    yesterday_date = _format_russian_date(yesterday)
    report_datetime = f"{_format_russian_date(local)}, {local:%H:%M}"
    return local, trading_date, yesterday_date, report_datetime


def _format_calendar_for_today(calendar, *, now: datetime, tz_name: str) -> str:
    from src.calendar.models import EconomicEvent

    local = now.astimezone(ZoneInfo(tz_name))
    today = local.date()
    today_events: list[EconomicEvent] = [
        event
        for event in calendar
        if event.event_at.date() == today
    ]
    today_events.sort(key=lambda event: event.event_at)

    lines = [
        f"**Календарь на { _format_russian_date(local) } (Europe/Warsaw):**",
        f"Событий сегодня: {len(today_events)}",
        "",
    ]
    if not today_events:
        lines.append("_На сегодня в календаре Investing.com нет событий средней+ важности._")
        return "\n".join(lines)

    for event in today_events[:25]:
        time_str = event.event_at.strftime("%H:%M")
        values = []
        if event.forecast:
            values.append(f"прогноз: {event.forecast}")
        if event.previous:
            values.append(f"пред.: {event.previous}")
        extra = f" ({'; '.join(values)})" if values else ""
        lines.append(
            f"- **{time_str}** | {event.country} ({event.currency}) | "
            f"важность: {event.importance} | {event.name}{extra}"
        )
    return "\n".join(lines)


def _clean_ai_section(text: str, key: str) -> str:
    cleaned = (text or "").strip()
    for prefix in (f"#{key}", f"## {key}"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].lstrip("\n")
            break
    cleaned = re.sub(
        rf"^#{{1,2}}\s*{re.escape(key)}\s*$",
        "",
        cleaned,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    for section_key in AI_SECTION_KEYS:
        cleaned = re.sub(
            rf"^#{{1,2}}\s*{re.escape(section_key)}\s*$",
            "",
            cleaned,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    return cleaned.strip()


def _parse_markdown_table_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """Разобрать markdown-таблицу: префикс до заголовка и строки ячеек."""
    lines = text.splitlines()
    prefix: list[str] = []
    rows: list[list[str]] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if not in_table:
                prefix.append(line)
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        if not in_table and "отрасль" in cells[0].lower():
            continue
        if not in_table and len(cells) >= 2 and "отрасль" in cells[1].lower():
            in_table = True
            rows.append(cells)
            continue
        if in_table:
            if cells[0].replace("-", "").replace(":", "").strip() == "":
                continue
            if cells[0] in {"№", "#"}:
                continue
            rows.append(cells)

    return prefix, rows


def _ensure_sector_ratings_coverage(
    sector_ratings: str,
    required_sectors: list[str],
) -> str:
    """Добавить в §2 отрасли портфеля/watchlist, пропущенные моделью."""
    if not required_sectors:
        return sector_ratings

    prefix, rows = _parse_markdown_table_rows(sector_ratings)
    if not rows:
        return sector_ratings

    header = rows[0]
    data_rows = rows[1:]
    existing_sectors = [
        cells[1]
        for cells in data_rows
        if len(cells) >= 4 and cells[1].lower() != "отрасль"
    ]

    missing = [
        sector
        for sector in required_sectors
        if not any(sector_matches(existing, sector) for existing in existing_sectors)
    ]
    if not missing:
        return sector_ratings

    next_no = 1
    for cells in data_rows:
        if len(cells) >= 1 and cells[0].isdigit():
            next_no = max(next_no, int(cells[0]) + 1)

    appended: list[str] = []
    for sector in missing:
        appended.append(
            f"| {next_no} | {sector} | 0 | Нет явных драйверов в новостях вчера |"
        )
        next_no += 1

    logger.warning(
        "§2: добавлены пропущенные отрасли (%d): %s",
        len(missing),
        ", ".join(missing),
    )

    table_lines = ["| " + " | ".join(header) + " |"]
    if len(header) >= 4:
        table_lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for cells in data_rows:
        table_lines.append("| " + " | ".join(cells) + " |")
    table_lines.extend(appended)

    parts = prefix + [""] + table_lines if prefix else table_lines
    return "\n".join(parts).strip()


async def _generate_ai_sections(
    filled_prompt: str,
    settings: Settings,
) -> tuple[dict[str, str], str]:
    model = settings.openai_model

    try:
        logger.info("Запрос к OpenAI, модель: %s", model)
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты аналитик мировых рынков. Отвечай на русском. "
                        "Строго следуй формату таблиц из инструкции. "
                        "Не добавляй служебные метки вида #top_market_news в текст. "
                        "Верни JSON с ключами: "
                        + ", ".join(AI_SECTION_KEYS)
                        + ". Каждое значение — markdown-текст для вставки в отчёт."
                    ),
                },
                {"role": "user", "content": filled_prompt},
            ],
            response_format={"type": "json_object"},
        )
        ai_sections = json.loads(response.choices[0].message.content or "{}")
        ai_sections = {
            key: _clean_ai_section(ai_sections.get(key, ""), key) for key in AI_SECTION_KEYS
        }
        _validate_ai_sections(ai_sections, AI_SECTION_KEYS)
        used_model = response.model or model
        logger.info("Брифинг сгенерирован через OpenAI (%s)", used_model)
        return ai_sections, used_model
    except ReportGenerationError:
        raise
    except Exception as e:
        logger.error("OpenAI недоступен (%s)", e)
        raise ReportGenerationError("OpenAI недоступен — отчёт не сформирован") from e


def render_report(
    news: list[NewsItem],
    ai_sections: dict[str, str],
    *,
    trading_date: str,
    yesterday_date: str,
    report_datetime: str,
    ai_model: str = "—",
) -> str:
    template_md = _load_template("template.md")
    report_template = Template(template_md)
    return report_template.render(
        trading_date=trading_date,
        yesterday_date=yesterday_date,
        report_datetime=report_datetime,
        news_count=len(news),
        ai_model=ai_model,
        **{key: ai_sections.get(key, "") for key in AI_SECTION_KEYS},
    )


async def generate_report(
    analytics: PortfolioAnalytics,
    news: list[NewsItem],
    settings: Settings,
    structure: StructureAnalysis | None = None,
    calendar=None,
) -> ReportResult:
    _require_openai(settings)
    yaml_cfg = load_yaml_config()
    tz_name = yaml_cfg.get("timezone", settings.timezone)
    now = datetime.now(ZoneInfo(tz_name))
    local, trading_date, yesterday_date, report_datetime = _briefing_dates(
        now, tz_name
    )

    screening_sectors = collect_screening_sectors(analytics, structure)
    news_context = format_news_for_prompt(news)
    interest_sectors_context = format_interest_sectors_for_prompt(
        analytics, structure, screening_sectors
    )
    companies_context = format_companies_for_prompt(structure)
    calendar_context = _format_calendar_for_today(
        calendar or [],
        now=local,
        tz_name=tz_name,
    )

    if not structure or (
        not structure.portfolio_holdings
        and not structure.watchlist_sectors
        and not structure.watchlist_tracking_holdings
    ):
        logger.warning(
            "Структура ETF пуста или не загружена — AI-анализ без входящих бумаг"
        )

    prompt_template = Template(_load_template("prompt.md"))
    filled_prompt = prompt_template.render(
        trading_date=trading_date,
        yesterday_date=yesterday_date,
        report_datetime=report_datetime,
        news_count=len(news),
        news_context=news_context,
        interest_sectors_context=interest_sectors_context,
        companies_context=companies_context,
        calendar_context=calendar_context,
    )

    ai_sections, ai_model = await _generate_ai_sections(filled_prompt, settings)
    ai_sections["sector_ratings"] = _ensure_sector_ratings_coverage(
        ai_sections.get("sector_ratings", ""),
        screening_sectors,
    )
    markdown = render_report(
        news,
        ai_sections,
        trading_date=trading_date,
        yesterday_date=yesterday_date,
        report_datetime=report_datetime,
        ai_model=ai_model,
    )
    metadata = ReportMetadata(
        id=local.strftime("%Y-%m-%d_%H%M%S"),
        created_at=local.astimezone(timezone.utc).isoformat(),
        trading_date=trading_date,
        yesterday_date=yesterday_date,
        ai_model=ai_model,
        portfolio_count=len(analytics.positions),
        news_total=len(news),
        watchlist_count=len(structure.watchlist_sectors) if structure else 0,
        calendar_events=len(calendar or []),
        screening_sectors=len(screening_sectors),
    )
    return ReportResult(markdown=markdown, metadata=metadata)
