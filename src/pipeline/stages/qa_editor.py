"""QA-1 Редактор: грамматика, терминология, стиль."""

from __future__ import annotations

import logging

from src.agents.base import call_json_agent
from src.agents.runner import load_agent_prompt, render_agent_prompt
from src.config import Settings, load_yaml_config
from src.pipeline.models import BriefingDraft, QARemark, QARemarks

logger = logging.getLogger(__name__)


def _parse_remarks(payload: dict, model: str) -> QARemarks:
    remarks: list[QARemark] = []
    for raw in payload.get("remarks", []):
        remarks.append(
            QARemark(
                section=str(raw.get("section", "")),
                location=str(raw.get("location", "")),
                issue=str(raw.get("issue", "")),
                suggestion=str(raw.get("suggestion", "")),
                severity=str(raw.get("severity", "medium")),
                approved=bool(raw.get("approved", True)),
            )
        )
    return QARemarks(remarks=remarks, model=model)


def format_remarks_for_prompt(remarks: QARemarks) -> str:
    approved = [r for r in remarks.remarks if r.approved]
    if not approved:
        return "_Замечаний нет._"
    lines = []
    for index, remark in enumerate(approved, 1):
        lines.append(
            f"{index}. [{remark.section}] {remark.location}: "
            f"{remark.issue} → {remark.suggestion} (severity: {remark.severity})"
        )
    return "\n".join(lines)


async def run_qa_editor(
    draft: BriefingDraft,
    settings: Settings,
) -> QARemarks:
    yaml_cfg = load_yaml_config()
    model = yaml_cfg.get("pipeline", {}).get("qa_editor_model") or None

    system_prompt = load_agent_prompt("qa_editor")
    user_prompt = render_agent_prompt(
        "qa_editor",
        **draft.sections,
    )

    payload, used_model = call_json_agent(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
    )
    result = _parse_remarks(payload, used_model)
    logger.info("QA-1 Editor (%s): %d замечаний", used_model, len(result.remarks))
    return result
