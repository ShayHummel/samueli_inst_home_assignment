"""LangChain prompt templates for the PD / Non-PD pipeline (assignment 2.2).

One module per pipeline stage. Each exposes ``SYSTEM_TEMPLATE``,
``USER_TEMPLATE``, a ready ``PROMPT`` (``ChatPromptTemplate``) and
``INPUT_VARIABLES``.

    from src.prompts import STAGE1_PROMPT
    messages = STAGE1_PROMPT.format_messages(note_text=note)
"""

from __future__ import annotations

from . import repair, self_check, stage1_reasoning, stage2_structuring
from ._util import JSON_CONTRACT, as_json_string, escape_braces

STAGE1_PROMPT = stage1_reasoning.PROMPT
STAGE2_PROMPT = stage2_structuring.PROMPT
REPAIR_PROMPT = repair.PROMPT
SELF_CHECK_PROMPT = self_check.PROMPT

__all__ = [
    "JSON_CONTRACT",
    "REPAIR_PROMPT",
    "SELF_CHECK_PROMPT",
    "STAGE1_PROMPT",
    "STAGE2_PROMPT",
    "as_json_string",
    "escape_braces",
    "repair",
    "self_check",
    "stage1_reasoning",
    "stage2_structuring",
]
