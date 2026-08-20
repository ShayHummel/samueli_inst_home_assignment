"""The PD / Non-PD classification flow (assignment 2.2 and 2.4).

One function, :func:`classify_note`, runs the five stages designed in Part 2:

    1. REASON     stage 1 prompt  -> prose analysis ending in a VERDICT line
    2. STRUCTURE  stage 2 prompt  -> strict JSON
    3. VALIDATE   code            -> Pydantic + verdict preservation + quote grounding
    4. REPAIR     repair prompt   -> bounded retries, structural failures only
    5. AUDIT      self-check      -> optional adversarial reasoning check

The LLM is injected as a plain callable, so the flow is fully testable without a
model and does not care whether it is talking to vLLM, Ollama, or a mock.

Run ``uv run samueli-pipeline`` for a four-scenario walkthrough against scripted
models: a clean run, a repair, an unrepairable failure, and an abstention.
"""

from __future__ import annotations

# Running this file by path (`python src/pipeline.py`, which is PyCharm's default run
# configuration) leaves __package__ unset, so the relative imports below have no
# parent package to resolve against and fail with an opaque ImportError. Checking
# __package__ specifically — rather than catching ImportError — means a genuinely
# missing dependency still reports itself accurately.
if not __package__:  # pragma: no cover - only reachable when run by file path
    raise SystemExit(
        "Run this as a module, not a file path:\n"
        "    uv run python -m src.pipeline\n"
        "or use the installed entry point:\n"
        "    uv run samueli-pipeline\n\n"
        "In PyCharm, set the run configuration's target to 'module name' "
        "(src.pipeline) instead of 'script path'."
    )

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage

from .prompts import (
    REPAIR_PROMPT,
    SELF_CHECK_PROMPT,
    STAGE1_PROMPT,
    STAGE2_PROMPT,
    as_json_string,
)
from .schema import ClinicalClassification
from .validation import (
    REPAIRABLE_FAILURES,
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
#: call to vLLM, or a scripted fake in a test. Deliberately the narrowest possible
#: interface: the flow needs no streaming, no tools and no async, so requiring
#: them would only make it harder to substitute a model.
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

    #: Raw model text per stage, kept so a failure can be diagnosed rather than
    #: guessed at. Without it, "schema_validation_error" tells you a record failed
    #: but not what the model actually said, which is the only thing that helps.
    transcript: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        # Lets callers write `if result:` instead of `if result.ok:`. The flow has
        # exactly one success condition, so collapsing it into truthiness removes a
        # class of bug where `if result:` silently passes on a failed record.
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
        max_repair_attempts: How many times to retry a structural failure. Bounded
            on purpose: an unbounded repair loop turns a broken model into a bill.
        fail_on_audit_rejection: If True, an audit that finds the classification
            unsupported marks the record failed. The parsed classification is still
            attached, so a caller can inspect what was rejected.
        tally: Optional counter; every failure is recorded by type.

    Returns:
        A :class:`PipelineResult`. Truthy on success.
    """
    # One model is the common case for a local deployment and for tests. In
    # production these differ: the expensive reasoning model runs once, and the
    # cheap extraction model absorbs formatting and any repair retries.
    structuring_llm = structuring_llm or reasoning_llm

    transcript: dict[str, str] = {}

    def finish(result: PipelineResult) -> PipelineResult:
        """Single exit point: attach the transcript and record the outcome.

        Every ``return`` below goes through here. That is the point — tallying at
        each return site would eventually miss one, and a failure that never
        reaches the tally is exactly the silent-failure mode 3.2 forbids.
        """
        result.transcript = transcript
        if tally is not None:
            tally.total += 1
            if not result.ok and result.failure_type is not None:
                tally.counts[result.failure_type] += 1
        return result

    # -- Stage 1: reason ---------------------------------------------------- #
    # Encoded once and reused by the stage 5 audit below. The note is delivered as
    # a JSON string value rather than inside XML-style tags so it cannot terminate
    # its own container and continue as instructions (see 2.7).
    note_as_json = as_json_string(note_text)
    stage1_raw = reasoning_llm(STAGE1_PROMPT.format_messages(note_json=note_as_json))
    transcript["stage1"] = stage1_raw

    # Stage 1's four closing lines are the machine contract. If the VERDICT line is
    # missing, stage 1 went off-contract and there is nothing for stage 2 to
    # preserve — so fail here rather than paying for a second call whose output
    # could not be checked for drift anyway.
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
    # Receives stage 1's output and *not* the note. That is a security property,
    # not an optimisation: it confines the prompt-injection surface to stage 1.
    stage2_raw = structuring_llm(STAGE2_PROMPT.format_messages(stage_one_output=stage1_raw))
    transcript["stage2"] = stage2_raw

    # -- Stage 3: validate, and Stage 4: repair on failure ------------------ #
    report = verify_output(stage2_raw, note_text, verdict)
    attempts = 0

    # Only *structural* failures are retried. VERDICT_DRIFT is excluded from
    # REPAIRABLE_FAILURES on purpose: repair may not change clinical content, so it
    # cannot legitimately resolve a disagreement about the verdict — and if it
    # could, a formatting retry would be making a clinical decision. Retrying it
    # would also burn two calls to arrive at the same failure.
    while (
        not report.ok
        and report.failure_type in REPAIRABLE_FAILURES
        and attempts < max_repair_attempts
    ):
        attempts += 1
        # The repair prompt is given the validator's *exact* error text. A model
        # told "confidence_score: input should be less than or equal to 100" can
        # fix it; one told "invalid JSON" guesses.
        stage2_raw = structuring_llm(
            REPAIR_PROMPT.format_messages(
                invalid_output=stage2_raw,
                validation_error=report.failure_detail,
            )
        )
        transcript[f"repair_{attempts}"] = stage2_raw
        # Re-validated rather than trusted. A repair call is just another model
        # call and can fail in a new way.
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

    # verify_output guarantees result is populated whenever ok is True; asserting
    # documents that invariant for readers and type checkers alike.
    assert report.result is not None
    classification = report.result

    # -- Stage 5: adversarial audit (optional) ------------------------------ #
    # Answers the question stage 3 cannot: do the quotes actually *support* the
    # verdict? Stage 3 checks a quote is present; entailment needs reasoning.
    self_check: SelfCheckOutcome | None = None
    if audit_llm is not None:
        # The auditor sees the note and the finished output, but never stage 1's
        # reasoning — shown the original argument, a reviewer tends to ratify it
        # rather than test it independently.
        audit_raw = audit_llm(
            SELF_CHECK_PROMPT.format_messages(
                note_json=note_as_json,
                candidate_json=classification.model_dump_json(indent=2),
            )
        )
        transcript["audit"] = audit_raw
        self_check = parse_self_check(audit_raw)

        # `self_check is not None` matters: an auditor that went off-contract
        # yields None, which is treated as *no audit* rather than as a pass. A
        # malformed audit must never silently approve a record it failed to judge.
        if self_check is not None and not self_check.supported and fail_on_audit_rejection:
            return finish(
                PipelineResult(
                    ok=False,
                    # The classification is still attached on rejection, so a caller
                    # can inspect and triage what the auditor objected to.
                    classification=classification,
                    failure_type=FailureType.SELF_CHECK_REJECTED,
                    failure_detail="; ".join(self_check.issues)
                    or "audit found the classification unsupported by the summary",
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
    """Run :func:`classify_note` over a corpus, tallying failures by type.

    Sequential on purpose. Concurrency belongs at the serving layer (vLLM batches
    internally), and adding it here would make the per-record failure accounting
    harder to reason about for no gain on a local deployment.
    """
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


# --------------------------------------------------------------------------- #
# Walkthrough
#
# Four scenarios against scripted models, so the flow — including its failure
# paths — can be seen end to end without a GPU. The failure scenarios matter more
# than the happy path: they are what the design is actually for.
# --------------------------------------------------------------------------- #


class _ScriptedLlm:  # pragma: no cover - demo helper
    """Returns queued responses in order, repeating the last once exhausted.

    Repeating the last response is what makes "never recovers" scenarios easy to
    script: give one bad response and every retry gets the same bad response.
    """

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, _messages: Sequence[BaseMessage]) -> str:
        self.calls += 1
        return self._responses[min(self.calls - 1, len(self._responses) - 1)]


def _stage1(verdict: str, confidence: str, evidence: str) -> str:  # pragma: no cover
    """A stage-1 response: the six-step prose, then the four machine-readable lines."""
    return (
        "1. LOCATE. ...\n2. SUBJECT. ...\n3. ASSERTION STATUS. ...\n"
        "4. TIMEPOINT. ...\n5. RESOLVE. ...\n6. DECIDE.\n\n"
        f"VERDICT: {verdict}\n"
        f"CONFIDENCE: {confidence}\n"
        f"EVIDENCE: {evidence}\n"
        "REASONING: See the analysis above."
    )


def _show(title: str, explanation: str, result: PipelineResult) -> None:  # pragma: no cover
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")
    print(f"{explanation}\n")
    print(f"  ok              : {result.ok}")
    if result.classification is not None:
        c = result.classification
        print(f"  classification  : {c.classification.value}")
        print(f"  confidence      : {c.confidence_score}   (output scale, 0.0-1.0)")
        print(f"  evidence quotes : {len(c.supporting_evidence)}")
        print(f"  abstention      : {c.is_abstention}")
    if not result.ok:
        print(f"  failure type    : {result.failure_type.value}")
        print(f"  failure detail  : {result.failure_detail[:120]}")
    print(f"  repair attempts : {result.repair_attempts}")
    print(f"  stages recorded : {', '.join(result.transcript)}")


def demo() -> int:  # pragma: no cover - illustrative walkthrough
    """Run four scenarios against scripted models. Entry point for `samueli-pipeline`."""
    pd_note = (
        "IMPRESSION: Restaging CT shows new hepatic lesions, consistent with "
        "progressive disease. If the patient progresses further we will consider "
        "second line. The patient's mother had progressive disease."
    )
    pd_quote = "new hepatic lesions, consistent with progressive disease"
    pd_stage1 = _stage1("PD", "92", f'"{pd_quote}"')

    def stage2_json(classification: str = "PD", confidence: str = "92") -> str:
        return (
            f'{{"classification": "{classification}", "confidence_score": {confidence}, '
            f'"supporting_evidence": ["{pd_quote}"], '
            f'"clinical_reasoning": "Current imaging documents new hepatic lesions."}}'
        )

    # --- 1. Clean run, through conversational noise ----------------------- #
    # Stage 2 wraps its JSON in a code fence with chatty text either side. That is
    # not a failure: brace-matched extraction strips it, so no repair is needed.
    _show(
        "1. Clean run — messy formatting absorbed without a repair call",
        "Stage 2 emitted a fenced block with prose on both sides. The extractor\n"
        "handles it, so this costs two model calls and zero retries.",
        classify_note(
            pd_note,
            reasoning_llm=_ScriptedLlm(pd_stage1),
            structuring_llm=_ScriptedLlm(
                f"Sure, here is the JSON:\n```json\n{stage2_json()}\n```\nHope that helps!"
            ),
        ),
    )

    # --- 2. Repair recovers a truncated object ---------------------------- #
    # Stage 2's first response is cut off mid-generation, which is a *structural*
    # failure and therefore repairable. The repair call receives the validator's
    # exact error and returns valid JSON.
    _show(
        "2. Repair — truncated JSON, recovered on the first retry",
        "Stage 2 was cut off mid-object (no_json_found). That is structural, so\n"
        "stage 4 runs, is handed the exact validator error, and succeeds.",
        classify_note(
            pd_note,
            reasoning_llm=_ScriptedLlm(pd_stage1),
            structuring_llm=_ScriptedLlm('{"classification": "PD", "confidence_sco', stage2_json()),
        ),
    )

    # --- 3. A validation failure that is deliberately NOT repaired -------- #
    # Stage 1 concluded PD; stage 2 emitted Non-PD. Repair is forbidden from
    # changing clinical content, so it cannot fix this — note repair_attempts is 0
    # even though retries were allowed.
    _show(
        "3. Verdict drift — fails immediately, no repair attempted",
        "Stage 1 said PD, stage 2 said Non-PD. Repair may not change clinical\n"
        "content, so drift is unrepairable by construction: it fails at once and\n"
        "repair_attempts stays 0 despite max_repair_attempts=3.",
        classify_note(
            pd_note,
            reasoning_llm=_ScriptedLlm(pd_stage1),
            structuring_llm=_ScriptedLlm(stage2_json(classification="Non-PD")),
            max_repair_attempts=3,
        ),
    )

    # --- 4. An uninformative note becomes an abstention ------------------- #
    # The D13 case, and per the EDA the *majority* of this corpus: nothing about
    # disease status. The output is Non-PD, but with a low confidence and no
    # evidence — the machine-detectable signature that routes it to a clinician
    # instead of counting it as a confident negative.
    quiet_note = (
        "PREOPERATIVE DIAGNOSIS: Right inguinal hernia. PROCEDURE: Open repair with "
        "mesh. ESTIMATED BLOOD LOSS: Minimal. The patient tolerated the procedure well."
    )
    _show(
        "4. Ambiguous note — Non-PD as an abstention, not a finding",
        "Nothing in this note bears on disease status (~69% of the corpus, per the\n"
        "EDA). Non-PD is emitted with confidence 10/100 and no evidence, which\n"
        "is_abstention detects so the record can be routed to a clinician.",
        classify_note(
            quiet_note,
            reasoning_llm=_ScriptedLlm(_stage1("Non-PD", "10", "NONE")),
            structuring_llm=_ScriptedLlm(
                '{"classification": "Non-PD", "confidence_score": 10, '
                '"supporting_evidence": [], '
                '"clinical_reasoning": "The summary contains no assessable content."}'
            ),
        ),
    )

    print(
        f"\n{'=' * 72}\n"
        "Scenarios 2-4 are the point: a clean run proves little, whereas repair,\n"
        "unrepairable drift and abstention are what the design exists to handle.\n"
        f"{'=' * 72}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(demo())
