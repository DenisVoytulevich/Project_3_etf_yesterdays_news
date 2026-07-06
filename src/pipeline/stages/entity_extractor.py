"""Entity Extractor: извлечение сущностей из новостей."""

from __future__ import annotations

import logging

from src.agents.base import call_json_agent
from src.agents.runner import load_agent_prompt, render_agent_prompt
from src.config import Settings, load_yaml_config
from src.pipeline.models import (
    ExtractedArticleEntities,
    ExtractedEntities,
    FocusContext,
    NewsBatch,
)

logger = logging.getLogger(__name__)


def _format_news_for_extraction(batch: NewsBatch) -> str:
    lines: list[str] = []
    for index, item in enumerate(batch.items):
        lines.append(f"### [{index}] {item.title} [{item.source}]")
        lines.append(item.summary[:400] or "—")
        if item.url:
            lines.append(f"URL: {item.url}")
        lines.append("")
    return "\n".join(lines)


def _parse_extracted(payload: dict, batch: NewsBatch) -> ExtractedEntities:
    articles: list[ExtractedArticleEntities] = []
    for raw in payload.get("articles", []):
        index = int(raw.get("news_index", -1))
        title = str(raw.get("title", ""))
        if index < 0 or index >= len(batch.items):
            continue
        articles.append(
            ExtractedArticleEntities(
                news_index=index,
                title=title or batch.items[index].title,
                companies=list(raw.get("companies") or []),
                etfs=[str(x) for x in raw.get("etfs") or []],
                countries=[str(x) for x in raw.get("countries") or []],
                currencies=[str(x) for x in raw.get("currencies") or []],
                commodities=[str(x) for x in raw.get("commodities") or []],
                events=list(raw.get("events") or []),
            )
        )
    return ExtractedEntities(articles=articles)


async def run_entity_extractor(
    batch: NewsBatch,
    focus: FocusContext,
    settings: Settings,
) -> ExtractedEntities:
    if not batch.items:
        logger.warning("Entity Extractor: нет новостей")
        return ExtractedEntities(articles=[])

    yaml_cfg = load_yaml_config()
    model = yaml_cfg.get("pipeline", {}).get("entity_extractor_model") or None

    system_prompt = load_agent_prompt("entity_extractor")
    user_prompt = render_agent_prompt(
        "entity_extractor",
        news_context=_format_news_for_extraction(batch),
        yesterday_date=focus.dates.yesterday_date,
    )
    # entity_extractor prompt is system-only; append news to user message
    user_prompt = (
        f"Новости за {focus.dates.yesterday_date}:\n\n"
        f"{_format_news_for_extraction(batch)}"
    )

    payload, used_model = call_json_agent(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
    )
    result = _parse_extracted(payload, batch)
    logger.info(
        "Entity Extractor (%s): %d статей, %d с сущностями",
        used_model,
        len(batch.items),
        len(result.articles),
    )
    return result
