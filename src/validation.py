"""Stage 3 — output verification (assignment 2.4 and 3.2).

`verify_output` is the single entry point. It takes the raw text stage 2 produced
and returns a :class:`VerificationReport` that either carries a validated
:class:`~src.schema.ClinicalClassification` or an explicit, typed failure.

Four checks, in the order that fails cheapest first:

1. **Extract** — find the JSON in output that may carry code fences or trailing prose.
2. **Parse** — ``json.loads``.
3. **Schema** — Pydantic, including the "PD needs evidence" rule.
4. **Semantics** — the two checks a schema cannot express:
   * *verdict preservation*: stage 2 must not have altered stage 1's verdict;
   * *evidence grounding*: every quote must really occur in the source note.

Every failure carries a :class:`FailureType`. That taxonomy exists because the
assignment is explicit that a silent ``except: pass`` is a failing answer — and
because "12 failures" is not actionable while "12 truncated JSON" and "12 verdict
drift" point at completely different bugs.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from pydantic import ValidationError

from .schema import Classification, ClinicalClassification


class FailureType(str, Enum):
    """Why a record failed. Counted per type so failures stay diagnosable."""

    NO_JSON_FOUND = "no_json_found"
    JSON_DECODE_ERROR = "json_decode_error"
    NOT_A_JSON_OBJECT = "not_a_json_object"
    SCHEMA_VALIDATION_ERROR = "schema_validation_error"
    VERDICT_DRIFT = "verdict_drift"
    EVIDENCE_NOT_IN_SOURCE = "evidence_not_in_source"
    STAGE1_NO_VERDICT = "stage1_no_verdict"
    SELF_CHECK_REJECTED = "self_check_rejected"


#: Failure types a repair call can plausibly fix. All of them are *structural*:
#: the model produced the right judgement in the wrong shape.
#:
#: ``VERDICT_DRIFT`` is deliberately **excluded**. Repair is forbidden from changing
#: clinical content, so it cannot legitimately resolve a disagreement about the
#: verdict — and if it were allowed to, a formatting retry would be silently making a
#: clinical decision. Drift means the formatter is unreliable on this record, which is
#: a fault to surface, not to paper over. Retrying it would also burn two calls to
#: arrive at the same failure.
REPAIRABLE_FAILURES = frozenset(
    {
        FailureType.NO_JSON_FOUND,
        FailureType.JSON_DECODE_ERROR,
        FailureType.NOT_A_JSON_OBJECT,
        FailureType.SCHEMA_VALIDATION_ERROR,
        # Repairable because a paraphrased quote is a formatting error: the repair
        # prompt tells the model to copy quotes character-for-character.
        FailureType.EVIDENCE_NOT_IN_SOURCE,
    }
)


@dataclass(frozen=True)
class Stage1Verdict:
    """The machine-readable tail of a stage 1 response."""

    classification: Classification
    confidence: float
    evidence: tuple[str, ...]
    reasoning: str


@dataclass(frozen=True)
class VerificationReport:
    """Outcome of verifying one record."""

    ok: bool
    result: ClinicalClassification | None = None
    failure_type: FailureType | None = None
    failure_detail: str = ""
    #: Quotes that could not be located in the source note, if any.
    ungrounded_quotes: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ok


# --------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_block(raw: str) -> str | None:
    """Pull the JSON object out of messy model output.

    Handles, in order: a fenced ``json`` code block; a bare object with prose
    before or after it. Returns ``None`` when there is no brace-delimited
    candidate at all.

    Brace matching is used rather than a greedy ``{.*}`` regex so that trailing
    prose containing a brace cannot drag the candidate past the real end of the
    object.
    """
    if not raw or not raw.strip():
        return None

    fenced = _FENCE_RE.search(raw)
    candidate = fenced.group(1) if fenced else raw

    start = candidate.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(candidate[start:], start=start):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return candidate[start : i + 1]
    # Unbalanced: the object was truncated mid-generation.
    return None


# --------------------------------------------------------------------------- #
# Stage 1 tail parsing
# --------------------------------------------------------------------------- #

_VERDICT_RE = re.compile(r"^VERDICT:\s*(PD|Non-PD)\s*$", re.MULTILINE | re.IGNORECASE)
_CONFIDENCE_RE = re.compile(r"^CONFIDENCE:\s*([0-9]*\.?[0-9]+)\s*$", re.MULTILINE)
_EVIDENCE_RE = re.compile(r"^EVIDENCE:\s*(.+?)\s*$", re.MULTILINE)
_REASONING_RE = re.compile(r"^REASONING:\s*(.+?)\s*$", re.MULTILINE | re.DOTALL)


def parse_stage1_verdict(stage1_output: str) -> Stage1Verdict | None:
    """Parse stage 1's four closing lines.

    Returns ``None`` if the verdict line is absent, which means stage 1 itself
    went off-contract and there is nothing for stage 2 to preserve. The last
    match wins for each field: a model that restates the block corrects itself
    at the end, and the prompt requires these to be the final lines.
    """
    verdicts = _VERDICT_RE.findall(stage1_output or "")
    if not verdicts:
        return None
    label = "PD" if verdicts[-1].upper() == "PD" else "Non-PD"

    confidences = _CONFIDENCE_RE.findall(stage1_output)
    try:
        confidence = float(confidences[-1]) if confidences else 0.0
    except ValueError:
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 100.0)

    evidence: tuple[str, ...] = ()
    ev_matches = _EVIDENCE_RE.findall(stage1_output)
    if ev_matches:
        raw_ev = ev_matches[-1].strip()
        if raw_ev.upper() != "NONE":
            evidence = tuple(
                q.strip().strip('"').strip()
                for q in raw_ev.split("|")
                if q.strip().strip('"').strip()
            )

    reasoning_matches = _REASONING_RE.findall(stage1_output)
    reasoning = reasoning_matches[-1].strip() if reasoning_matches else ""

    return Stage1Verdict(
        classification=Classification(label),
        confidence=confidence,
        evidence=evidence,
        reasoning=reasoning,
    )


# --------------------------------------------------------------------------- #
# Self-check tail parsing
# --------------------------------------------------------------------------- #

_SUPPORTED_RE = re.compile(r"^SUPPORTED:\s*(yes|no)\s*$", re.MULTILINE | re.IGNORECASE)
_CONF_ASSESS_RE = re.compile(
    r"^CONFIDENCE_ASSESSMENT:\s*(appropriate|overconfident|underconfident)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_ISSUES_RE = re.compile(r"^ISSUES:\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class SelfCheckOutcome:
    """Verdict of the adversarial reasoning audit (``src.prompts.self_check``)."""

    supported: bool
    confidence_assessment: str
    issues: tuple[str, ...] = ()


def parse_self_check(text: str) -> SelfCheckOutcome | None:
    """Parse the auditor's three closing lines. ``None`` if it went off-contract."""
    supported = _SUPPORTED_RE.findall(text or "")
    if not supported:
        return None

    assessment = _CONF_ASSESS_RE.findall(text)
    issue_lines = _ISSUES_RE.findall(text)
    issues: tuple[str, ...] = ()
    if issue_lines:
        raw = issue_lines[-1].strip()
        if raw.upper() != "NONE":
            issues = tuple(i.strip() for i in raw.split(";") if i.strip())

    return SelfCheckOutcome(
        supported=supported[-1].lower() == "yes",
        confidence_assessment=(assessment[-1].lower() if assessment else "appropriate"),
        issues=issues,
    )


# --------------------------------------------------------------------------- #
# Evidence grounding
# --------------------------------------------------------------------------- #

_WS_RE = re.compile(r"\s+")
# Literal JSON escape sequences, collapsed so a quote reproduced in escaped form
# still matches its source. See prompts._util.as_json_string.
_JSON_ESCAPES = ((r"\n", " "), (r"\t", " "), (r"\r", " "), (r'\"', '"'), (r"\\", "\\"))

_PUNCT_MAP = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"',
        "–": "-", "—": "-", "―": "-", "−": "-",
        " ": " ", "…": "...",
    }
)


def normalise_for_matching(text: str) -> str:
    """Canonicalise text for substring comparison.

    Collapses whitespace, folds case, and maps Unicode punctuation variants onto
    ASCII. Punctuation is *normalised, not stripped* — deleting it would let
    "no progression" match "progression", turning a negation into a false
    positive, which is precisely the error this pipeline exists to avoid.
    """
    text = unicodedata.normalize("NFKC", text)
    for escaped, plain in _JSON_ESCAPES:
        text = text.replace(escaped, plain)
    text = text.translate(_PUNCT_MAP)
    text = _WS_RE.sub(" ", text)
    return text.strip().casefold()


def find_ungrounded_quotes(quotes: list[str] | tuple[str, ...], note_text: str) -> tuple[str, ...]:
    """Return the quotes that do not occur in ``note_text``.

    This is the first half of the Q1.2e faithfulness check: a quote absent from
    the source means the model fabricated its own evidence. Whether a *present*
    quote actually supports the verdict is the second half, and needs reasoning —
    see ``src.prompts.self_check``.
    """
    haystack = normalise_for_matching(note_text)
    return tuple(q for q in quotes if normalise_for_matching(q) not in haystack)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def verify_output(
    raw_output: str,
    note_text: str,
    stage1_verdict: Stage1Verdict | Classification | str | None = None,
) -> VerificationReport:
    """Verify one stage-2 output end to end.

    Args:
        raw_output: Stage 2's raw text, possibly fenced or with trailing prose.
        note_text: The source clinical summary, for grounding the quotes.
        stage1_verdict: Stage 1's verdict, to detect drift. Accepts a
            :class:`Stage1Verdict`, a :class:`~src.schema.Classification`, or the
            label as a string. ``None`` skips the drift check — appropriate only
            when there is no stage 1 to compare against, such as a single-call
            baseline.

    Returns:
        A :class:`VerificationReport`. Truthy on success.
    """
    block = extract_json_block(raw_output)
    if block is None:
        return VerificationReport(
            ok=False,
            failure_type=FailureType.NO_JSON_FOUND,
            failure_detail="no balanced JSON object found (empty, prose-only, or truncated)",
        )

    try:
        payload = json.loads(block)
    except json.JSONDecodeError as exc:
        return VerificationReport(
            ok=False,
            failure_type=FailureType.JSON_DECODE_ERROR,
            failure_detail=f"{exc.msg} at line {exc.lineno} column {exc.colno}",
        )

    if not isinstance(payload, dict):
        return VerificationReport(
            ok=False,
            failure_type=FailureType.NOT_A_JSON_OBJECT,
            failure_detail=f"expected a JSON object, got {type(payload).__name__}",
        )

    try:
        result = ClinicalClassification.model_validate(payload)
    except ValidationError as exc:
        return VerificationReport(
            ok=False,
            failure_type=FailureType.SCHEMA_VALIDATION_ERROR,
            failure_detail=str(exc),
        )

    expected = _coerce_expected_label(stage1_verdict)
    if expected is not None and result.classification is not expected:
        return VerificationReport(
            ok=False,
            failure_type=FailureType.VERDICT_DRIFT,
            failure_detail=(
                f"stage 1 concluded {expected.value!r} but stage 2 emitted "
                f"{result.classification.value!r}; the formatting step must not change "
                f"the clinical verdict"
            ),
        )

    ungrounded = find_ungrounded_quotes(result.supporting_evidence, note_text)
    if ungrounded:
        return VerificationReport(
            ok=False,
            failure_type=FailureType.EVIDENCE_NOT_IN_SOURCE,
            failure_detail=(
                f"{len(ungrounded)} of {len(result.supporting_evidence)} evidence quotes "
                f"do not occur in the source note"
            ),
            ungrounded_quotes=ungrounded,
        )

    return VerificationReport(ok=True, result=result)


def _coerce_expected_label(
    verdict: Stage1Verdict | Classification | str | None,
) -> Classification | None:
    if verdict is None:
        return None
    if isinstance(verdict, Stage1Verdict):
        return verdict.classification
    if isinstance(verdict, Classification):
        return verdict
    return Classification(verdict)


# --------------------------------------------------------------------------- #
# Failure accounting
# --------------------------------------------------------------------------- #


@dataclass
class FailureTally:
    """Counts failures by type across a run.

    Exists so the pipeline can report *what* went wrong and how often, rather
    than a bare success rate. Required by 3.2's "count failures by error type".
    """

    counts: Counter[FailureType] = field(default_factory=Counter)
    total: int = 0

    def record(self, report: VerificationReport) -> VerificationReport:
        self.total += 1
        if not report.ok and report.failure_type is not None:
            self.counts[report.failure_type] += 1
        return report

    @property
    def failures(self) -> int:
        return sum(self.counts.values())

    @property
    def successes(self) -> int:
        return self.total - self.failures

    def as_dict(self) -> dict[str, int]:
        return {ft.value: self.counts.get(ft, 0) for ft in FailureType}

    def summary(self) -> str:
        lines = [
            f"records: {self.total}",
            f"valid:   {self.successes}",
            f"failed:  {self.failures}",
        ]
        if self.failures:
            lines.append("by type:")
            lines += [
                f"  {name}: {count}"
                for name, count in sorted(self.as_dict().items(), key=lambda kv: -kv[1])
                if count
            ]
        return "\n".join(lines)
