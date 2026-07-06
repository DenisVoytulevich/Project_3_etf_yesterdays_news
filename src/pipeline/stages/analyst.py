"""Analyst: анализ влияния и черновик отчёта."""

from __future__ import annotations

import logging

from src.agents.base import call_json_agent
from src.agents.runner import load_agent_prompt, render_agent_prompt
from src.config import Settings, load_yaml_config
from src.news.aggregator import format_news_for_prompt
from src.pipeline.models import (
    BRIEFING_SECTION_KEYS,
    BriefingDraft,
    FocusContext,
    NewsBatch,
    NormalizedEntities,
)
from src.pipeline.stages.theme_normalizer import format_normalized_for_prompt
from src.report.markdown_tables import clean_ai_section

logger = logging.getLogger(__name__)


async def run_analyst(
    normalized: NormalizedEntities,
    batch: NewsBatch,
    focus: FocusContext,
    settings: Settings,
) -> BriefingDraft:
    yaml_cfg = load_yaml_config()
    model = yaml_cfg.get("pipeline", {}).get("analyst_model") or None

    system_prompt = load_agent_prompt("analyst")
    user_prompt = render_agent_prompt(
        "analyst",
        impact_scale=load_agent_prompt("impact_scale"),
        trading_date=focus.dates.trading_date,
        yesterday_date=focus.dates.yesterday_date,
        report_datetime=focus.dates.report_datetime,
        normalized_entities_context=format_normalized_for_prompt(normalized),
        news_context=format_news_for_prompt(batch.items),
        interest_sectors_context=focus.interest_sectors_context,
        companies_context=focus.companies_context,
        calendar_context=focus.calendar_context,
    )

    payload, used_model = call_json_agent(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
    )
    sections = {
        key: clean_ai_section(str(payload.get(key, "")), key)
        for key in BRIEFING_SECTION_KEYS
    }
    logger.info("Analyst (%s): черновик отчёта сформирован", used_model)
    return BriefingDraft(sections=sections, model=used_model)
