"""Tests for the end-to-end classification flow.

The LLM is a scripted callable throughout: each fake returns a queued response
per call, so the repair loop can be driven deterministically (fail, then fix).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from langchain_core.messages import BaseMessage

from src.pipeline import classify_note, classify_notes
from src.schema import Classification
from src.validation import FailureType

NOTE_PD = (
    "IMPRESSION: Restaging CT shows new hepatic lesions, consistent with progressive "
    "disease. If the patient progresses further we will consider second line. The "
    "patient's mother had progressive disease."
)
NOTE_SILENT = "CHIEF COMPLAINT: Routine follow-up. Patient reports feeling well. Labs pending."


class ScriptedLlm:
    """Returns queued responses in order; repeats the last one once exhausted."""

    def __init__(self, *responses: str) -> None:
        assert responses, "a scripted LLM needs at least one response"
        self._responses = list(responses)
        self.calls: list[Sequence[BaseMessage]] = []

    def __call__(self, messages: Sequence[BaseMessage]) -> str:
        self.calls.append(messages)
        i = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[i]


def stage1_text(
    verdict: str = "PD",
    confidence: str = "0.92",
    evidence: str = '"new hepatic lesions, consistent with progressive disease"',
) -> str:
    return (
        "1. LOCATE. ...\n2. SUBJECT. ...\n3. ASSERTION STATUS. ...\n"
        "4. TIMEPOINT. ...\n5. RESOLVE. ...\n6. DECIDE.\n\n"
        f"VERDICT: {verdict}\nCONFIDENCE: {confidence}\n"
        f"EVIDENCE: {evidence}\nREASONING: Current imaging documents new hepatic lesions."
    )


def stage2_json(
    classification: str = "PD",
    confidence: str = "0.92",
    evidence: str = '"new hepatic lesions, consistent with progressive disease"',
) -> str:
    return (
        f'{{"classification": "{classification}", "confidence_score": {confidence}, '
        f'"supporting_evidence": [{evidence}], '
        f'"clinical_reasoning": "Current imaging documents new hepatic lesions."}}'
    )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_clean_run_succeeds():
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(stage2_json()),
    )
    assert result
    assert result.classification.classification is Classification.PD
    assert result.repair_attempts == 0
    assert set(result.transcript) == {"stage1", "stage2"}


def test_messy_output_is_absorbed_without_repair():
    """Fenced block plus conversational filler on both sides is still stage-2 valid."""
    messy = f"Certainly! Here you go:\n```json\n{stage2_json()}\n```\nAnything else?"
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(messy),
    )
    assert result
    assert result.repair_attempts == 0


def test_note_text_reaches_the_stage1_prompt_but_not_stage2():
    """Stage 2 must never see the note — that confines the injection surface."""
    reasoner, structurer = ScriptedLlm(stage1_text()), ScriptedLlm(stage2_json())
    classify_note(NOTE_PD, reasoning_llm=reasoner, structuring_llm=structurer)

    stage1_blob = "".join(m.content for m in reasoner.calls[0])
    stage2_blob = "".join(m.content for m in structurer.calls[0])
    assert "new hepatic lesions" in stage1_blob
    assert "Restaging CT" not in stage2_blob


# --------------------------------------------------------------------------- #
# Stage 1 contract
# --------------------------------------------------------------------------- #


def test_stage1_without_a_verdict_line_fails_early():
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm("I think it's probably progression, hard to say."),
        structuring_llm=ScriptedLlm(stage2_json()),
    )
    assert not result
    assert result.failure_type is FailureType.STAGE1_NO_VERDICT


def test_stage2_is_not_called_when_stage1_fails():
    structurer = ScriptedLlm(stage2_json())
    classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm("no verdict here"),
        structuring_llm=structurer,
    )
    assert structurer.calls == []


# --------------------------------------------------------------------------- #
# Repair loop
# --------------------------------------------------------------------------- #


def test_repair_recovers_from_a_truncated_object():
    structurer = ScriptedLlm(
        '{"classification": "PD", "confidence_sco',  # truncated
        stage2_json(),  # repair call fixes it
    )
    result = classify_note(
        NOTE_PD, reasoning_llm=ScriptedLlm(stage1_text()), structuring_llm=structurer
    )
    assert result
    assert result.repair_attempts == 1
    assert "repair_1" in result.transcript


def test_repair_prompt_receives_the_concrete_validator_error():
    """A model told the actual error can fix it; one told "invalid" guesses."""
    structurer = ScriptedLlm(stage2_json(confidence="1.7"), stage2_json())
    classify_note(NOTE_PD, reasoning_llm=ScriptedLlm(stage1_text()), structuring_llm=structurer)

    repair_blob = "".join(m.content for m in structurer.calls[1])
    assert "confidence_score" in repair_blob
    assert "less than or equal to 1" in repair_blob


def test_repair_attempts_are_bounded():
    structurer = ScriptedLlm("not json at all")  # never recovers
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=structurer,
        max_repair_attempts=2,
    )
    assert not result
    assert result.repair_attempts == 2
    assert len(structurer.calls) == 3  # 1 structuring + 2 repairs


def test_repair_disabled_fails_immediately():
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm("garbage"),
        max_repair_attempts=0,
    )
    assert not result
    assert result.repair_attempts == 0


# --------------------------------------------------------------------------- #
# Verdict drift and grounding, through the flow
# --------------------------------------------------------------------------- #


def test_verdict_drift_survives_repair_and_fails():
    """Repair may not launder a changed verdict into a pass."""
    drifted = stage2_json(classification="Non-PD")
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text(verdict="PD")),
        structuring_llm=ScriptedLlm(drifted),
    )
    assert not result
    assert result.failure_type is FailureType.VERDICT_DRIFT


def test_fabricated_evidence_fails_the_record():
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(stage2_json(evidence='"widespread bone metastases"')),
    )
    assert not result
    assert result.failure_type is FailureType.EVIDENCE_NOT_IN_SOURCE


# --------------------------------------------------------------------------- #
# D13 abstention
# --------------------------------------------------------------------------- #


def test_uninformative_note_yields_a_recognised_abstention():
    stage1 = stage1_text(verdict="Non-PD", confidence="0.1", evidence="NONE")
    stage2 = (
        '{"classification": "Non-PD", "confidence_score": 0.1, '
        '"supporting_evidence": [], '
        '"clinical_reasoning": "The summary contains no assessable content."}'
    )
    result = classify_note(
        NOTE_SILENT, reasoning_llm=ScriptedLlm(stage1), structuring_llm=ScriptedLlm(stage2)
    )
    assert result
    assert result.classification.is_abstention


# --------------------------------------------------------------------------- #
# Adversarial audit
# --------------------------------------------------------------------------- #

AUDIT_PASS = "All six checks pass.\n\nSUPPORTED: yes\nCONFIDENCE_ASSESSMENT: appropriate\nISSUES: NONE"
AUDIT_FAIL = (
    "The quote is drawn from a hypothetical clause.\n\n"
    "SUPPORTED: no\nCONFIDENCE_ASSESSMENT: overconfident\n"
    "ISSUES: quote is hypothetical; omits a contradicting statement"
)


def test_audit_pass_keeps_the_record():
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(stage2_json()),
        audit_llm=ScriptedLlm(AUDIT_PASS),
    )
    assert result
    assert result.self_check is not None and result.self_check.supported


def test_audit_rejection_fails_the_record_but_keeps_the_output():
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(stage2_json()),
        audit_llm=ScriptedLlm(AUDIT_FAIL),
    )
    assert not result
    assert result.failure_type is FailureType.SELF_CHECK_REJECTED
    assert result.classification is not None  # still inspectable
    assert "hypothetical" in result.failure_detail


def test_audit_rejection_can_be_downgraded_to_a_flag():
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(stage2_json()),
        audit_llm=ScriptedLlm(AUDIT_FAIL),
        fail_on_audit_rejection=False,
    )
    assert result
    assert result.self_check is not None and not result.self_check.supported


def test_malformed_audit_is_treated_as_no_audit_not_as_approval():
    result = classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(stage2_json()),
        audit_llm=ScriptedLlm("Looks fine to me!"),
    )
    assert result
    assert result.self_check is None


def test_audit_sees_the_note_and_the_output_but_not_stage1_reasoning():
    """An auditor shown the original argument tends to ratify it."""
    auditor = ScriptedLlm(AUDIT_PASS)
    classify_note(
        NOTE_PD,
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(stage2_json()),
        audit_llm=auditor,
    )
    blob = "".join(m.content for m in auditor.calls[0])
    assert "Restaging CT" in blob
    assert "classification" in blob
    assert "6. DECIDE" not in blob


# --------------------------------------------------------------------------- #
# Corpus helper
# --------------------------------------------------------------------------- #


def test_classify_notes_tallies_failures_by_type():
    results, tally = classify_notes(
        [NOTE_PD, NOTE_PD, NOTE_PD],
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(stage2_json(classification="Non-PD")),
        max_repair_attempts=0,
    )
    assert len(results) == 3
    assert tally.total == 3
    assert tally.successes == 0
    assert tally.as_dict()[FailureType.VERDICT_DRIFT.value] == 3


def test_tally_mixes_successes_and_failures():
    _, tally = classify_notes(
        [NOTE_PD],
        reasoning_llm=ScriptedLlm(stage1_text()),
        structuring_llm=ScriptedLlm(stage2_json()),
    )
    assert tally.total == 1 and tally.successes == 1 and tally.failures == 0
