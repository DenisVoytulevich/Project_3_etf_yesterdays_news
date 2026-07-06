"""Revision Agent: внесение замечаний QA без смены структуры."""

from __future__ import annotations

import logging

from src.agents.base import call_json_agent
from src.agents.runner import load_agent_prompt, render_agent_prompt
from src.config import Settings, load_yaml_config
from src.pipeline.models import (
    BRIEFING_SECTION_KEYS,
    BriefingDraft,
    QARemarks,
)
from src.pipeline.stages.qa_editor import format_remarks_for_prompt
from src.report.markdown_tables import clean_ai_section

logger = logging.getLogger(__name__)


async def run_revision_agent(
    draft: BriefingDraft,
    editor_qa: QARemarks,
    analytics_qa: QARemarks,
    settings: Settings,
) -> BriefingDraft:
    approved_count = sum(
        1
        for remark in editor_qa.remarks + analytics_qa.remarks
        if remark.approved
    )
    if approved_count == 0:
        logger.info("Revision Agent: замечаний нет, черновик без изменений")
        return draft

    yaml_cfg = load_yaml_config()
    model = yaml_cfg.get("pipeline", {}).get("revision_model") or None

    system_prompt = load_agent_prompt("revision_agent")
    user_prompt = render_agent_prompt(
        "revision_agent",
        editor_remarks_context=format_remarks_for_prompt(editor_qa),
        analytics_remarks_context=format_remarks_for_prompt(analytics_qa),
        **draft.sections,
    )

    payload, used_model = call_json_agent(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
    )
    sections = {
        key: clean_ai_section(str(payload.get(key, draft.sections.get(key, ""))), key)
        for key in BRIEFING_SECTION_KEYS
    }
    logger.info("Revision Agent (%s): внесено %d замечаний", used_model, approved_count)
    return BriefingDraft(sections=sections, model=used_model)
