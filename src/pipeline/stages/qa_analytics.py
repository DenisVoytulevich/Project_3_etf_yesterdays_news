"""QA-2 Аналитика: логика, причинность, соответствие новостям."""

from __future__ import annotations

import logging

from src.agents.base import call_json_agent
from src.agents.runner import load_agent_prompt, render_agent_prompt
from src.config import Settings, load_yaml_config
from src.news.aggregator import format_news_for_prompt
from src.pipeline.models import (
    BriefingDraft,
    FocusContext,
    NewsBatch,
    NormalizedEntities,
    QARemarks,
)
from src.pipeline.stages.qa_editor import _parse_remarks
from src.pipeline.stages.theme_normalizer import format_normalized_for_prompt

logger = logging.getLogger(__name__)


async def run_qa_analytics(
    draft: BriefingDraft,
    normalized: NormalizedEntities,
    batch: NewsBatch,
    focus: FocusContext,
    settings: Settings,
) -> QARemarks:
    yaml_cfg = load_yaml_config()
    model = yaml_cfg.get("pipeline", {}).get("qa_analytics_model") or None

    system_prompt = load_agent_prompt("qa_analytics")
    user_prompt = render_agent_prompt(
        "qa_analytics",
        news_context=format_news_for_prompt(batch.items),
        normalized_entities_context=format_normalized_for_prompt(normalized),
        **draft.sections,
    )

    payload, used_model = call_json_agent(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
    )
    result = _parse_remarks(payload, used_model)
    logger.info("QA-2 Analytics (%s): %d замечаний", used_model, len(result.remarks))
    return result
