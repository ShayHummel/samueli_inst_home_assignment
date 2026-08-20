"""Content assertions on the prompts.

These are not style checks. Each pins a decision that a future edit could silently
reverse, where the reversal would break nothing else in the suite.
"""

from __future__ import annotations

import re

from src.prompts import repair, self_check, stage1_reasoning, stage2_structuring


def flat(text: str) -> str:
    """Collapse whitespace, so these assertions survive re-wrapping the prompt."""
    return re.sub(r"\s+", " ", text)


def test_stage1_permits_medical_knowledge_for_interpretation():
    """A blanket "no outside medical knowledge" would be self-defeating.

    Reading these notes requires knowing that PR is a response category and that
    "new hepatic lesions" means growth. The constraint has to scope to *supplying
    facts*, not to interpretation.
    """
    t = flat(stage1_reasoning.SYSTEM_TEMPLATE)
    assert "Use your clinical knowledge freely to READ" in t
    assert "Do NOT use it to SUPPLY facts" in t


def test_stage1_forbids_reasoning_from_what_is_typical():
    """The genuinely dangerous use of outside knowledge: population priors."""
    t = flat(stage1_reasoning.SYSTEM_TEMPLATE)
    assert "never reason from" in t
    assert "typical" in t
    assert "THIS patient" in t


def test_auditor_also_permits_interpretation():
    """Judging entailment is entirely a knowledge task, so the auditor needs it too."""
    t = flat(self_check.SYSTEM_TEMPLATE)
    assert "Use your clinical knowledge to interpret" in t
    assert "supply facts the summary does not contain" in t


def test_no_prompt_bans_medical_knowledge_outright():
    """Guards the exact wording that was wrong, across every prompt."""
    for module in (stage1_reasoning, stage2_structuring, repair, self_check):
        assert "Do not use outside medical knowledge" not in flat(module.SYSTEM_TEMPLATE), (
            f"{module.__name__} bans medical knowledge outright"
        )


def test_stage1_still_requires_a_quotable_basis():
    """The latitude above is only safe because grounding is enforced separately."""
    t = flat(stage1_reasoning.SYSTEM_TEMPLATE)
    assert "you must be able to quote that something" in t
    assert "copied character-for-character" in t


def test_stage2_remains_a_formatter_with_no_judgement():
    t = flat(stage2_structuring.SYSTEM_TEMPLATE)
    assert "NO clinical judgement" in t
    assert "do not change the verdict" in t.lower()
