"""The PD / Non-PD classification flow (assignment 2.2 and 2.4).

One function, :func:`classify_note`, runs the four stages designed in Part 2:

    1. REASON     stage 1 prompt  -> prose analysis ending in a VERDICT line
    2. STRUCTURE  stage 2 prompt  -> strict JSON
    3. VALIDATE   code            -> Pydantic + verdict preservation + quote grounding
    4. REPAIR     repair prompt   -> bounded retries on validation failure
    5. AUDIT      self-check      -> optional adversarial reasoning check

The LLM is injected as a plain callable, so the flow is fully testable without a
model and does not care whether it is talking to vLLM, Ollama, or a mock.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage

from .prompts import REPAIR_PROMPT, SELF_CHECK_PROMPT, STAGE1_PROMPT, STAGE2_PROMPT
from .schema import ClinicalClassification
from .validation import (
    FailureTally,
    FailureType,
    SelfCheckOutcome,
    Stage1Verdict,
    parse_self_check,
    parse_stage1_verdict,
    verify_output,
)

#: A local model call: messages in, raw completion text out. Anything that
#: satisfies this works — a LangChain chat model wrapped in a lambda, an HTTP
#: call to vLLM, or a scripted fake in a test.
LlmCallable = Callable[[Sequence[BaseMessage]], str]


@dataclass
class PipelineResult:
    """What happened to one clinical summary, including the audit trail."""

    ok: bool
    classification: ClinicalClassification | None = None
    failure_type: FailureType | None = None
    failure_detail: str = ""

    stage1_verdict: Stage1Verdict | None = None
    self_check: SelfCheckOutcome | None = None
    repair_attempts: int = 0

    #: Raw model text, kept so a failure can be diagnosed rather than guessed at.
    transcript: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok


def classify_note(
    note_text: str,
    *,
    reasoning_llm: LlmCallable,
    structuring_llm: LlmCallable | None = None,
    audit_llm: LlmCallable | None = None,
    max_repair_attempts: int = 2,
    fail_on_audit_rejection: bool = True,
    tally: FailureTally | None = None,
) -> PipelineResult:
    """Classify one clinical summary as PD or Non-PD.

    Args:
        note_text: The clinical summary. Untrusted input; never treated as instructions.
        reasoning_llm: Model for stage 1. Should be the reasoning tier.
        structuring_llm: Model for stages 2 and 4. Defaults to ``reasoning_llm``;
            in production this is the cheaper extraction tier.
        audit_llm: Optional model for the stage 5 adversarial audit. Should be a
            *different model family* from ``reasoning_llm`` — sharing a model means
            sharing blind spots, so the audit would ratify the errors it exists to
            catch (see Q1.2d on correlated judge errors). Omit to skip the audit.
        max_repair_attempts: How many times to retry a schema failure. Bounded on
            purpose: an unbounded repair loop turns a broken model into a bill.
        fail_on_audit_rejection: If True, an audit that finds the classification
            unsupported marks the record failed. The parsed classification is still
            attached, so a caller can inspect what was rejected.
        tally: Optional counter; every failure is recorded by type.

    Returns:
        A :class:`PipelineResult`. Truthy on success.
    """
    structuring_llm = structuring_llm or reasoning_llm
    transcript: dict[str, str] = {}

    def finish(result: PipelineResult) -> PipelineResult:
        result.transcript = transcript
        if tally is not None:
            tally.total += 1
            if not result.ok and result.failure_type is not None:
                tally.counts[result.failure_type] += 1
        return result

    # -- Stage 1: reason ---------------------------------------------------- #
    stage1_raw = reasoning_llm(STAGE1_PROMPT.format_messages(note_text=note_text))
    transcript["stage1"] = stage1_raw

    verdict = parse_stage1_verdict(stage1_raw)
    if verdict is None:
        return finish(
            PipelineResult(
                ok=False,
                failure_type=FailureType.STAGE1_NO_VERDICT,
                failure_detail="stage 1 produced no parseable VERDICT line",
            )
        )

    # -- Stage 2: structure ------------------------------------------------- #
    stage2_raw = structuring_llm(
        STAGE2_PROMPT.format_messages(stage_one_output=stage1_raw)
    )
    transcript["stage2"] = stage2_raw

    # -- Stage 3: validate, and Stage 4: repair on failure ------------------ #
    report = verify_output(stage2_raw, note_text, verdict)
    attempts = 0
    while not report.ok and attempts < max_repair_attempts:
        attempts += 1
        stage2_raw = structuring_llm(
            REPAIR_PROMPT.format_messages(
                invalid_output=stage2_raw,
                validation_error=report.failure_detail,
            )
        )
        transcript[f"repair_{attempts}"] = stage2_raw
        report = verify_output(stage2_raw, note_text, verdict)

    if not report.ok:
        return finish(
            PipelineResult(
                ok=False,
                failure_type=report.failure_type,
                failure_detail=report.failure_detail,
                stage1_verdict=verdict,
                repair_attempts=attempts,
            )
        )

    assert report.result is not None  # guaranteed by report.ok
    classification = report.result

    # -- Stage 5: adversarial audit (optional) ------------------------------ #
    self_check: SelfCheckOutcome | None = None
    if audit_llm is not None:
        audit_raw = audit_llm(
            SELF_CHECK_PROMPT.format_messages(
                note_text=note_text,
                candidate_json=classification.model_dump_json(indent=2),
            )
        )
        transcript["audit"] = audit_raw
        self_check = parse_self_check(audit_raw)

        # An auditor that went off-contract is treated as no audit rather than as
        # a pass, so a malformed audit can never silently approve a record.
        if self_check is not None and not self_check.supported and fail_on_audit_rejection:
            return finish(
                PipelineResult(
                    ok=False,
                    classification=classification,
                    failure_type=FailureType.SELF_CHECK_REJECTED,
                    failure_detail="; ".join(self_check.issues) or "audit found the "
                    "classification unsupported by the summary",
                    stage1_verdict=verdict,
                    self_check=self_check,
                    repair_attempts=attempts,
                )
            )

    return finish(
        PipelineResult(
            ok=True,
            classification=classification,
            stage1_verdict=verdict,
            self_check=self_check,
            repair_attempts=attempts,
        )
    )


def classify_notes(
    notes: Sequence[str],
    *,
    reasoning_llm: LlmCallable,
    structuring_llm: LlmCallable | None = None,
    audit_llm: LlmCallable | None = None,
    max_repair_attempts: int = 2,
) -> tuple[list[PipelineResult], FailureTally]:
    """Run :func:`classify_note` over a corpus, tallying failures by type."""
    tally = FailureTally()
    results = [
        classify_note(
            note,
            reasoning_llm=reasoning_llm,
            structuring_llm=structuring_llm,
            audit_llm=audit_llm,
            max_repair_attempts=max_repair_attempts,
            tally=tally,
        )
        for note in notes
    ]
    return results, tally


if __name__ == "__main__":  # pragma: no cover - illustrative walkthrough
    # A scripted stand-in for a local model, so the flow can be seen end to end
    # without a GPU. Stage 2 deliberately emits a fenced block with trailing
    # prose, which is exactly the mess the validator is built to absorb.
    note = (
        "IMPRESSION: Restaging CT shows new hepatic lesions, consistent with "
        "progressive disease. If the patient progresses further we will consider "
        "second line. The patient's mother had progressive disease."
    )

    def fake_reasoner(_messages: Sequence[BaseMessage]) -> str:
        return (
            "1. LOCATE. 'new hepatic lesions, consistent with progressive disease'\n"
            "2. SUBJECT. The mother's history is discarded.\n"
            "3. ASSERTION STATUS. Asserted. The second-line sentence is HYPOTHETICAL.\n"
            "4. TIMEPOINT. Current restaging study.\n"
            "5. RESOLVE. No conflict.\n"
            "6. DECIDE.\n\n"
            "VERDICT: PD\n"
            "CONFIDENCE: 0.92\n"
            'EVIDENCE: "new hepatic lesions, consistent with progressive disease"\n'
            "REASONING: Current imaging documents new hepatic lesions."
        )

    def fake_structurer(_messages: Sequence[BaseMessage]) -> str:
        return (
            "Sure, here is the JSON:\n```json\n"
            '{"classification": "PD", "confidence_score": 0.92,\n'
            ' "supporting_evidence": ["new hepatic lesions, consistent with progressive disease"],\n'
            ' "clinical_reasoning": "Current imaging documents new hepatic lesions."}\n'
            "```\nHope that helps!"
        )

    result = classify_note(note, reasoning_llm=fake_reasoner, structuring_llm=fake_structurer)
    print(f"ok               : {result.ok}")
    print(f"classification   : {result.classification.classification.value}")
    print(f"confidence       : {result.classification.confidence_score}")
    print(f"evidence grounded: {len(result.classification.supporting_evidence)} quote(s)")
    print(f"repair attempts  : {result.repair_attempts}")
