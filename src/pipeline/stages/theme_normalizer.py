"""Theme Normalizer: нормализация сущностей по словарям."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from src.agents.base import call_json_agent
from src.agents.runner import load_agent_prompt, render_agent_prompt
from src.config import Settings, get_project_root, load_yaml_config
from src.pipeline.models import (
    ExtractedEntities,
    FocusContext,
    NormalizedEntities,
    NormalizedEntity,
)
from src.structure.labels import SECTOR_ALIASES

logger = logging.getLogger(__name__)


def _load_themes_database() -> str:
    path = get_project_root() / "data" / "generated" / "themes.yaml"
    if not path.is_file():
        return "_База тем не найдена._"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return yaml.dump(data, allow_unicode=True, default_flow_style=False)


def _format_sector_aliases() -> str:
    lines = []
    for sector, aliases in sorted(SECTOR_ALIASES.items()):
        lines.append(f"- {sector}: {', '.join(aliases[:8])}")
    return "\n".join(lines)


def _format_extracted(entities: ExtractedEntities) -> str:
    return json.dumps(
        [
            {
                "news_index": article.news_index,
                "title": article.title,
                "companies": article.companies,
                "etfs": article.etfs,
                "countries": article.countries,
                "currencies": article.currencies,
                "commodities": article.commodities,
                "events": article.events,
            }
            for article in entities.articles
        ],
        ensure_ascii=False,
        indent=2,
    )


def _parse_normalized(payload: dict) -> NormalizedEntities:
    entities: list[NormalizedEntity] = []
    for raw in payload.get("entities", []):
        entities.append(
            NormalizedEntity(
                source_news_index=int(raw.get("source_news_index", -1)),
                entity_type=str(raw.get("entity_type", "")),
                raw_name=str(raw.get("raw_name", "")),
                canonical_name=str(raw.get("canonical_name", "")),
                sector=str(raw.get("sector", "")),
                gics=str(raw.get("gics", "")),
                theme=str(raw.get("theme", "")),
                etf_ticker=str(raw.get("etf_ticker", "")),
            )
        )
    return NormalizedEntities(
        entities=entities,
        theme_notes=[str(x) for x in payload.get("theme_notes") or []],
    )


def format_normalized_for_prompt(entities: NormalizedEntities) -> str:
    if not entities.entities:
        return "_Нормализованные сущности отсутствуют._"
    lines = []
    for entity in entities.entities[:80]:
        parts = [
            entity.entity_type,
            entity.canonical_name or entity.raw_name,
        ]
        if entity.sector:
            parts.append(f"sector={entity.sector}")
        if entity.theme:
            parts.append(f"theme={entity.theme}")
        lines.append(f"- [{' | '.join(parts)}] (news #{entity.source_news_index})")
    if entities.theme_notes:
        lines.append("")
        lines.append("Примечания:")
        lines.extend(f"- {note}" for note in entities.theme_notes)
    return "\n".join(lines)


async def run_theme_normalizer(
    extracted: ExtractedEntities,
    focus: FocusContext,
    settings: Settings,
) -> NormalizedEntities:
    yaml_cfg = load_yaml_config()
    model = yaml_cfg.get("pipeline", {}).get("theme_normalizer_model") or None

    system_prompt = load_agent_prompt("theme_normalizer")
    user_prompt = render_agent_prompt(
        "theme_normalizer",
        themes_context=_load_themes_database(),
        interest_sectors_context=focus.interest_sectors_context,
        companies_context=focus.companies_context,
        sector_aliases_context=_format_sector_aliases(),
    )
    user_prompt += (
        "\n\n## Извлечённые сущности\n"
        f"{_format_extracted(extracted)}"
    )

    payload, used_model = call_json_agent(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
    )
    result = _parse_normalized(payload)
    logger.info(
        "Theme Normalizer (%s): %d сущностей, %d примечаний",
        used_model,
        len(result.entities),
        len(result.theme_notes),
    )
    return result
