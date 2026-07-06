"""Consistency Validator: техническая проверка JSON перед публикацией."""

from __future__ import annotations

import logging

from src.config import load_yaml_config
from src.pipeline.models import (
    BRIEFING_SECTION_KEYS,
    BriefingDraft,
    ConsistencyIssue,
    FocusContext,
    ValidatedBriefing,
)
from src.report.impact_scale import IMPACT_MAX, IMPACT_MIN, is_valid_impact_score, parse_impact_score
from src.companies.context import build_unified_company_list, company_identity_key
from src.report.markdown_tables import (
    finalize_portfolio_companies_news,
    finalize_sector_ratings,
    parse_markdown_table_rows,
)
from src.structure.labels import normalize_required_sectors, sector_matches

logger = logging.getLogger(__name__)

_RISK_TYPES = frozenset({"макро", "цб", "отчёт", "геополитика", "регуляторика"})


def _impact_range() -> tuple[int, int]:
    yaml_cfg = load_yaml_config()
    impact_cfg = yaml_cfg.get("impact_scale", yaml_cfg.get("sector_rating", {}))
    return int(impact_cfg.get("min", IMPACT_MIN)), int(impact_cfg.get("max", IMPACT_MAX))


def _check_impact_cell(
    raw: str,
    *,
    section: str,
    label: str,
    min_score: int,
    max_score: int,
) -> ConsistencyIssue | None:
    if not raw or raw in {"—", "-"}:
        return ConsistencyIssue(
            code="impact_missing",
            message=f"{label}: влияние не указано",
            section=section,
        )
    if not is_valid_impact_score(raw):
        score = parse_impact_score(raw)
        if score is None:
            return ConsistencyIssue(
                code="invalid_impact",
                message=f"{label}: неверный формат влияния «{raw}»",
                section=section,
            )
        return ConsistencyIssue(
            code="impact_out_of_range",
            message=f"{label}: влияние {score} вне {min_score}…{max_score}",
            section=section,
        )
    return None


def _check_required_sections(sections: dict[str, str]) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    for key in BRIEFING_SECTION_KEYS:
        if not (sections.get(key) or "").strip():
            issues.append(
                ConsistencyIssue(
                    code="empty_section",
                    message=f"Секция {key} пуста",
                    section=key,
                )
            )
    return issues


def _top_market_impact_col_from_header(rows: list[list[str]]) -> int:
    if not rows:
        return 1
    header = [c.strip().lower() for c in rows[0]]
    if header and header[0] == "#":
        return 2
    for index, name in enumerate(header):
        if name in {"сила", "влияние", "сила события"}:
            return index
    return 1


def _check_top_market_news(section: str, *, min_score: int, max_score: int) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    _, rows = parse_markdown_table_rows(section)
    if len(rows) < 2:
        return issues
    impact_col = _top_market_impact_col_from_header(rows)
    for row_index, cells in enumerate(rows[1:], start=1):
        if len(cells) <= impact_col:
            continue
        impact_raw = cells[impact_col].strip()
        if impact_raw.lower() in {"влияние", "сила события", "сила", "#"}:
            continue
        issue = _check_impact_cell(
            impact_raw,
            section="top_market_news",
            label=f"§1 строка {row_index}",
            min_score=min_score,
            max_score=max_score,
        )
        if issue:
            issues.append(issue)
    return issues


def _check_sector_ratings(
    sector_ratings: str,
    *,
    min_score: int,
    max_score: int,
    required_sectors: list[str],
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    _, rows = parse_markdown_table_rows(sector_ratings)
    if len(rows) < 2:
        issues.append(
            ConsistencyIssue(
                code="sector_table_missing",
                message="§2: таблица влияния по отраслям отсутствует или пуста",
                section="sector_ratings",
            )
        )
        return issues

    data_rows = rows[1:]
    seen_sectors: list[str] = []
    for row_index, cells in enumerate(data_rows, start=1):
        if len(cells) < 3:
            continue
        sector = cells[1].strip()
        impact_raw = cells[2].strip()
        if sector.lower() == "отрасль":
            continue
        if any(sector_matches(seen, sector) for seen in seen_sectors):
            issues.append(
                ConsistencyIssue(
                    code="duplicate_sector",
                    message=f"§2: дубль отрасли «{sector}»",
                    section="sector_ratings",
                )
            )
        seen_sectors.append(sector)

        if not sector or sector == "—":
            issues.append(
                ConsistencyIssue(
                    code="sector_without_name",
                    message=f"§2 строка {row_index}: пустая отрасль",
                    section="sector_ratings",
                )
            )

        issue = _check_impact_cell(
            impact_raw,
            section="sector_ratings",
            label=f"§2 «{sector}»",
            min_score=min_score,
            max_score=max_score,
        )
        if issue:
            issues.append(issue)

    for required in required_sectors:
        if not any(sector_matches(existing, required) for existing in seen_sectors):
            issues.append(
                ConsistencyIssue(
                    code="missing_required_sector",
                    message=f"§2: отсутствует обязательная отрасль «{required}»",
                    section="sector_ratings",
                )
            )

    return issues


def _check_portfolio_companies(
    portfolio_section: str,
    *,
    min_score: int,
    max_score: int,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    _, rows = parse_markdown_table_rows(portfolio_section)
    if len(rows) < 2:
        return issues

    placeholder = "значимых новостей по компаниям списка не выявлено"
    data_rows = rows[1:]
    seen_company_keys: set[str] = set()

    for cells in data_rows:
        if len(cells) < 5:
            continue
        company = cells[0].strip()
        sector = cells[2].strip()
        impact_raw = cells[4].strip()

        if placeholder in cells[3].lower():
            continue
        if company in {"—", ""}:
            continue

        company_key = company_identity_key(company)
        if company_key in seen_company_keys:
            issues.append(
                ConsistencyIssue(
                    code="duplicate_company",
                    message=f"§3: дубль компании «{company}»",
                    section="portfolio_companies_news",
                )
            )
        seen_company_keys.add(company_key)

        if not sector or sector == "—":
            issues.append(
                ConsistencyIssue(
                    code="company_without_sector",
                    message=f"§3 «{company}»: нет отрасли",
                    section="portfolio_companies_news",
                )
            )

        issue = _check_impact_cell(
            impact_raw,
            section="portfolio_companies_news",
            label=f"§3 «{company}»",
            min_score=min_score,
            max_score=max_score,
        )
        if issue:
            issues.append(issue)

    return issues


def _check_key_risks(
    key_risks: str,
    *,
    min_score: int,
    max_score: int,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    _, rows = parse_markdown_table_rows(key_risks)
    if len(rows) < 2:
        issues.append(
            ConsistencyIssue(
                code="risks_table_missing",
                message="§4: таблица рисков отсутствует",
                section="key_risks_today",
            )
        )
        return issues

    for row_index, cells in enumerate(rows[1:], start=1):
        if len(cells) < 4:
            continue
        risk_type = cells[2].strip().lower()
        impact_raw = cells[3].strip()
        if risk_type and risk_type not in _RISK_TYPES and risk_type != "—":
            issues.append(
                ConsistencyIssue(
                    code="invalid_risk_type",
                    message=f"§4: неверный тип «{cells[2].strip()}»",
                    section="key_risks_today",
                )
            )
        issue = _check_impact_cell(
            impact_raw,
            section="key_risks_today",
            label=f"§4 строка {row_index}",
            min_score=min_score,
            max_score=max_score,
        )
        if issue:
            issues.append(issue)
    return issues


def run_consistency_validator(
    draft: BriefingDraft,
    focus: FocusContext,
) -> ValidatedBriefing:
    min_score, max_score = _impact_range()

    required_sectors = normalize_required_sectors(focus.screening_sectors)

    sections = dict(draft.sections)
    sections["sector_ratings"] = finalize_sector_ratings(
        sections.get("sector_ratings", ""),
        required_sectors,
    )
    tracked_companies = build_unified_company_list(focus.structure)
    sections["portfolio_companies_news"] = finalize_portfolio_companies_news(
        sections.get("portfolio_companies_news", ""),
        required_sectors=required_sectors,
        tracked_companies=tracked_companies,
    )

    issues: list[ConsistencyIssue] = []
    issues.extend(_check_required_sections(sections))
    issues.extend(
        _check_top_market_news(
            sections.get("top_market_news", ""),
            min_score=min_score,
            max_score=max_score,
        )
    )
    issues.extend(
        _check_sector_ratings(
            sections.get("sector_ratings", ""),
            min_score=min_score,
            max_score=max_score,
            required_sectors=required_sectors,
        )
    )
    issues.extend(
        _check_portfolio_companies(
            sections.get("portfolio_companies_news", ""),
            min_score=min_score,
            max_score=max_score,
        )
    )
    issues.extend(
        _check_key_risks(
            sections.get("key_risks_today", ""),
            min_score=min_score,
            max_score=max_score,
        )
    )

    if issues:
        logger.warning(
            "Consistency Validator: %d проблем(ы): %s",
            len(issues),
            "; ".join(issue.message for issue in issues[:5]),
        )
    else:
        logger.info("Consistency Validator: проверка пройдена")

    return ValidatedBriefing(
        sections=sections,
        issues=issues,
        model=draft.model,
    )
