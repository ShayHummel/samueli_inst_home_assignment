"""Task 3.2 — evaluation pipeline over `Oncology.csv`.

    uv run python -m src.evaluate

Does what the assignment asks, in order: random binary labels for testing the
evaluation code, a mocked local-LLM call, robust parsing and schema validation with
failures counted by type, then a confusion matrix, precision/recall/F1 for the PD
class, and ROC-AUC from the confidence scores.

Three things here are deliberate rather than incidental:

* **Records with no ground truth and records that failed parsing are excluded from
  the metrics and the exclusion is reported.** Quietly dropping them inflates every
  score, because the dropped rows are not a random sample — they are the hard ones.
  See 3.3.
* **The confidence score is converted to P(PD) before ROC-AUC.** The model reports
  confidence in *whichever label it chose*, so feeding it directly to `roc_auc_score`
  scores a confident Non-PD as if it were evidence for PD.
* **Bootstrap confidence intervals are reported alongside the point estimates.** At
  n=90 with ~5% prevalence the intervals are wide enough that a point estimate on its
  own would misinform — exactly the Q1.2f failure mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support, roc_auc_score

from .eda import load
from .schema import ABSTENTION_CONFIDENCE_CEILING, Classification
from .validation import FailureTally, FailureType, verify_output

#: Label encoding fixed by the assignment: 0 = Non-PD, 1 = PD.
LABEL_NON_PD, LABEL_PD = 0, 1

DEFAULT_SEED = 20260819


# --------------------------------------------------------------------------- #
# Ground truth
# --------------------------------------------------------------------------- #


def add_random_labels(
    df: pd.DataFrame,
    *,
    seed: int = DEFAULT_SEED,
    pd_prevalence: float = 0.05,
    missing_rate: float = 0.0,
) -> pd.DataFrame:
    """Attach a random binary ground-truth column.

    Random by instruction: these labels exist to exercise the evaluation code, not
    to measure clinical accuracy. Any metric computed against them is a test of the
    harness. The report says so explicitly rather than presenting the numbers as
    performance.

    ``pd_prevalence`` defaults to 0.05 to match the ~5% positive class in Q1.2c,
    which the EDA found to be realistic for this corpus rather than hypothetical.

    ``missing_rate`` injects ``NaN`` ground truth, so the "records with no ground
    truth" path from 3.3 can actually be exercised instead of merely described.
    """
    rng = np.random.default_rng(seed)
    labels = rng.binomial(1, pd_prevalence, size=len(df)).astype(float)
    if missing_rate > 0:
        labels[rng.random(len(df)) < missing_rate] = np.nan

    out = df.copy()
    out["ground_truth"] = labels
    return out


# --------------------------------------------------------------------------- #
# Mocked local LLM
# --------------------------------------------------------------------------- #


def call_local_llm(text: str, *, seed: int | None = None) -> dict:
    """Simulate the Part-2 output for one note. The signature the assignment asks for.

    Returns a well-formed dict. Determinism is keyed off the note text so the same
    note always yields the same answer, which is what makes the pipeline
    reproducible (Part 2.6).
    """
    rng = np.random.default_rng(seed if seed is not None else _text_seed(text))
    return _draw_payload(text, rng)


def call_local_llm_messy(text: str, *, seed: int | None = None) -> str:
    """Simulate *raw* model output, including the ways real output is malformed.

    This exists because a mock that only ever returns clean dicts cannot test the
    parser, and the assignment is explicit that robust parsing is being assessed:
    "fenced code blocks, trailing prose, truncated or invalid JSON". The pipeline
    calls this rather than :func:`call_local_llm` so those paths are genuinely
    exercised and show up in the failure tally.

    Failure modes are drawn with fixed probabilities:

    ==========================  =====  ==================================
    mode                        prob   what it tests
    ==========================  =====  ==================================
    clean JSON                  0.55   happy path
    fenced in a code block      0.15   fence stripping
    trailing / leading prose    0.12   brace-matched extraction
    truncated mid-object        0.06   ``no_json_found``
    invalid JSON (trailing ,)   0.05   ``json_decode_error``
    confidence out of range     0.04   ``schema_validation_error``
    unknown extra field         0.03   ``extra="forbid"``
    ==========================  =====  ==================================
    """
    rng = np.random.default_rng(seed if seed is not None else _text_seed(text))
    payload = _draw_payload(text, rng)
    body = json.dumps(payload, indent=2)

    mode = rng.choice(
        ["clean", "fenced", "prose", "truncated", "invalid", "out_of_range", "extra_field"],
        p=[0.55, 0.15, 0.12, 0.06, 0.05, 0.04, 0.03],
    )
    if mode == "clean":
        return body
    if mode == "fenced":
        return f"```json\n{body}\n```"
    if mode == "prose":
        return (
            "Certainly. Based on my reading of the summary:\n\n"
            f"{body}\n\nLet me know if you would like me to reconsider any of this."
        )
    if mode == "truncated":
        return body[: max(12, int(len(body) * 0.6))]
    if mode == "invalid":
        return body.replace('",\n', '",,\n', 1)
    if mode == "out_of_range":
        bad = dict(payload, confidence_score=round(float(rng.uniform(1.01, 1.9)), 2))
        return json.dumps(bad, indent=2)
    return json.dumps(dict(payload, model_version="mock-0.1"), indent=2)


def _text_seed(text: str) -> int:
    """A stable seed derived from the note, so results do not depend on row order.

    Uses SHA-256 rather than the builtin ``hash()``. Python salts string hashing
    per process (PEP 456) unless ``PYTHONHASHSEED`` is pinned, so ``hash(text)``
    yields different values on every run — which silently made this pipeline
    irreproducible and changed the failure tally between invocations. Precisely the
    class of hidden non-determinism Part 2.6 warns about, found by running the thing
    twice and noticing the numbers moved.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def _draw_payload(text: str, rng: np.random.Generator) -> dict:
    """Build one plausible Part-2 payload for a note.

    Mirrors the real corpus rather than drawing uniformly: the EDA found ~69% of
    notes carry no status vocabulary at all, so most draws here are the D13
    abstention shape (Non-PD, low confidence, no evidence). A mock that produced a
    confident label for every note would hide the abstention path entirely.
    """
    quote = _pick_quote(text, rng)

    if quote is None:
        return {
            "classification": Classification.NON_PD.value,
            "confidence_score": round(float(rng.uniform(0.05, ABSTENTION_CONFIDENCE_CEILING)), 2),
            "supporting_evidence": [],
            "clinical_reasoning": "The summary contains no assessable statement about "
            "disease status or treatment response.",
        }

    is_pd = bool(rng.random() < 0.25)
    return {
        "classification": (Classification.PD if is_pd else Classification.NON_PD).value,
        "confidence_score": round(float(rng.uniform(0.60, 0.97)), 2),
        "supporting_evidence": [quote],
        "clinical_reasoning": (
            "Imaging findings quoted above document disease progression."
            if is_pd
            else "The quoted status statement indicates no current progression."
        ),
    }


#: Status vocabulary, ordered most to least specific. Kept short on purpose: every
#: quote must appear verbatim in the note or the grounding check will reject it.
_QUOTE_TERMS = (
    "progressive disease",
    "no evidence of",
    "stable disease",
    "partial response",
    "complete response",
    "remission",
    "progression",
    "metastatic",
)


def _pick_quote(text: str, rng: np.random.Generator) -> str | None:
    """Extract a real substring of the note to use as supporting evidence.

    Real substrings matter: the pipeline's grounding check rejects any quote absent
    from the source, so a mock that invented evidence would make every record fail
    for the wrong reason and tell us nothing about the parser.
    """
    lowered = text.lower()
    found = [t for t in _QUOTE_TERMS if t in lowered]
    if not found:
        return None
    term = found[int(rng.integers(len(found)))]
    start = lowered.index(term)
    # Widen to a clause so the quote reads like evidence rather than a keyword.
    left = text.rfind(" ", 0, max(0, start - 25)) + 1
    right = text.find(" ", start + len(term) + 25)
    right = right if right != -1 else len(text)
    return text[left:right].strip(" ,.;:")


# --------------------------------------------------------------------------- #
# Running the corpus
# --------------------------------------------------------------------------- #


@dataclass
class RunOutcome:
    """Per-record pipeline results plus the failure accounting."""

    frame: pd.DataFrame
    tally: FailureTally = field(default_factory=FailureTally)

    @property
    def valid(self) -> pd.DataFrame:
        return self.frame[self.frame["parse_ok"]]


def run_pipeline(df: pd.DataFrame, *, messy: bool = True) -> RunOutcome:
    """Classify every transcription, validating each output.

    Args:
        df: Frame with a ``transcription`` column and a ``ground_truth`` column.
        messy: If True (the default) use the messy raw-text mock so the robust
            parsing and repair paths are exercised. False uses the clean dict mock.
    """
    tally = FailureTally()
    rows: list[dict] = []

    for _, record in df.iterrows():
        note = record["transcription"]

        if messy:
            raw = call_local_llm_messy(note)
        else:
            raw = json.dumps(call_local_llm(note))

        report = tally.record(verify_output(raw, note, stage1_verdict=None))

        row = {
            "source_row_id": record.get("source_row_id"),
            "ground_truth": record.get("ground_truth"),
            "parse_ok": report.ok,
            "failure_type": report.failure_type.value if report.failure_type else None,
            "failure_detail": report.failure_detail or None,
            "predicted_label": None,
            "confidence_score": None,
            "p_pd": None,
            "is_abstention": None,
            "n_evidence": None,
        }
        if report.ok and report.result is not None:
            result = report.result
            predicted = (
                LABEL_PD if result.classification is Classification.PD else LABEL_NON_PD
            )
            row.update(
                predicted_label=predicted,
                confidence_score=result.confidence_score,
                p_pd=probability_of_pd(
                    predicted, result.confidence_score, is_abstention=result.is_abstention
                ),
                is_abstention=result.is_abstention,
                n_evidence=len(result.supporting_evidence),
            )
        rows.append(row)

    return RunOutcome(frame=pd.DataFrame(rows), tally=tally)


#: Score given to an abstention: exactly uninformative, so every abstention ties
#: with every other and contributes no discrimination either way.
UNINFORMATIVE_SCORE = 0.5


def probability_of_pd(
    predicted_label: int, confidence: float, *, is_abstention: bool = False
) -> float:
    """Convert "confidence in my chosen label" into P(PD).

    The schema's ``confidence_score`` is confidence in whichever label the model
    picked, not the probability of the positive class. Passing it straight to
    ``roc_auc_score`` treats a confident **Non-PD** as strong evidence *for* PD,
    which silently inverts half the ranking.

    **Abstentions need special handling, and getting this wrong is easy.** The D13
    signature is ``Non-PD`` with a *low* confidence, meaning "the note says
    nothing". Under the naive mapping that becomes ``1 - 0.1 = 0.9``, i.e. "almost
    certainly PD" — the exact opposite of what it means. Because the EDA found ~69%
    of this corpus has no assessable content, that single sign error dominates the
    ranking and drove observed ROC-AUC to 0.08 against random labels, which is well
    outside anything chance could produce.

    So an abstention is mapped to a constant :data:`UNINFORMATIVE_SCORE`. Ties carry
    no ranking information, which is the honest encoding of "no evidence". The more
    informative figure is ROC-AUC over the records the model *did* commit on,
    reported alongside coverage — the selective-prediction framing from Q1.2c.
    """
    if is_abstention:
        return UNINFORMATIVE_SCORE
    return confidence if predicted_label == LABEL_PD else 1.0 - confidence


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


@dataclass
class Metrics:
    """Evaluation results, with the record accounting that makes them interpretable."""

    n_total: int
    n_parse_failed: int
    n_missing_ground_truth: int
    n_evaluated: int
    n_positive: int
    confusion: np.ndarray | None
    precision: float | None
    recall: float | None
    f1: float | None
    roc_auc: float | None
    f1_ci: tuple[float, float] | None = None
    roc_auc_ci: tuple[float, float] | None = None
    n_abstentions: int = 0
    #: ROC-AUC restricted to records the model committed on (selective prediction).
    roc_auc_committed: float | None = None
    n_committed: int = 0

    def render(self) -> str:
        lines = ["Record accounting", "-" * 68]
        lines.append(f"  records in corpus                 {self.n_total}")
        lines.append(f"  excluded - parse/validation failed {self.n_parse_failed}")
        lines.append(f"  excluded - no ground truth         {self.n_missing_ground_truth}")
        lines.append(f"  evaluated                          {self.n_evaluated}")
        lines.append(f"  of which PD (positive class)       {self.n_positive}")
        lines.append(f"  abstentions among valid outputs    {self.n_abstentions}")

        if self.n_evaluated == 0 or self.confusion is None:
            lines.append("\nNo evaluable records — metrics undefined.")
            return "\n".join(lines)

        tn, fp, fn, tp = self.confusion.ravel()
        lines += [
            "",
            "Confusion matrix (rows = truth, cols = predicted)",
            "-" * 68,
            "                 pred Non-PD   pred PD",
            f"  true Non-PD    {tn:>11}   {fp:>7}",
            f"  true PD        {fn:>11}   {tp:>7}",
            "",
            "PD-class metrics",
            "-" * 68,
            f"  precision  {_fmt(self.precision)}",
            f"  recall     {_fmt(self.recall)}",
            f"  f1         {_fmt(self.f1)}{_fmt_ci(self.f1_ci)}",
            f"  roc-auc    {_fmt(self.roc_auc)}{_fmt_ci(self.roc_auc_ci)}",
        ]
        coverage = self.n_committed / self.n_evaluated if self.n_evaluated else 0.0
        lines += [
            "",
            "Selective prediction (abstentions excluded)",
            "-" * 68,
            f"  committed on   {self.n_committed} of {self.n_evaluated} "
            f"({coverage:.0%} coverage)",
            f"  roc-auc        {_fmt(self.roc_auc_committed)}",
        ]
        if self.n_positive < 10:
            lines += [
                "",
                f"  NOTE: only {self.n_positive} positive case(s). These intervals are wide",
                "  enough that the point estimates should not be quoted alone.",
            ]
        return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.3f}"


def _fmt_ci(ci: tuple[float, float] | None) -> str:
    return "" if ci is None else f"   95% CI [{ci[0]:.3f}, {ci[1]:.3f}]"


def evaluate(
    outcome: RunOutcome,
    *,
    bootstrap: int = 2000,
    seed: int = DEFAULT_SEED,
) -> Metrics:
    """Compute metrics, excluding unusable records and reporting the exclusions."""
    frame = outcome.frame
    n_total = len(frame)
    n_parse_failed = int((~frame["parse_ok"]).sum())

    valid = frame[frame["parse_ok"]]
    n_missing_gt = int(valid["ground_truth"].isna().sum())

    evaluable = valid[valid["ground_truth"].notna()]
    n_abstentions = int(valid["is_abstention"].fillna(False).astype(bool).sum())

    if evaluable.empty:
        return Metrics(
            n_total=n_total,
            n_parse_failed=n_parse_failed,
            n_missing_ground_truth=n_missing_gt,
            n_evaluated=0,
            n_positive=0,
            confusion=None,
            precision=None,
            recall=None,
            f1=None,
            roc_auc=None,
            n_abstentions=n_abstentions,
        )

    y_true = evaluable["ground_truth"].astype(int).to_numpy()
    y_pred = evaluable["predicted_label"].astype(int).to_numpy()
    y_score = evaluable["p_pd"].astype(float).to_numpy()

    cm = confusion_matrix(y_true, y_pred, labels=[LABEL_NON_PD, LABEL_PD])
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=[LABEL_PD], average="binary", pos_label=LABEL_PD,
        zero_division=0.0,
    )

    # ROC-AUC is undefined with a single class present; say so rather than crashing
    # or reporting a meaningless 0.5.
    roc_auc = (
        float(roc_auc_score(y_true, y_score)) if len(np.unique(y_true)) == 2 else None
    )

    f1_ci, auc_ci = _bootstrap_cis(y_true, y_pred, y_score, n=bootstrap, seed=seed)

    # The more informative figure: discrimination over the records the model
    # actually committed on. Abstentions are tied at UNINFORMATIVE_SCORE and can
    # only dilute the AUC toward 0.5, so reporting coverage alongside is essential
    # for the number to mean anything.
    # astype(bool) is required: the column is object dtype because it holds
    # None for failed records, and `~` on an object Series does bitwise
    # negation (-1/-2) rather than logical not.
    abstained = evaluable["is_abstention"].fillna(False).astype(bool)
    committed = evaluable[~abstained]
    roc_auc_committed = None
    if len(committed) >= 2:
        ct = committed["ground_truth"].astype(int).to_numpy()
        if len(np.unique(ct)) == 2:
            roc_auc_committed = float(
                roc_auc_score(ct, committed["p_pd"].astype(float).to_numpy())
            )

    return Metrics(
        n_total=n_total,
        n_parse_failed=n_parse_failed,
        n_missing_ground_truth=n_missing_gt,
        n_evaluated=len(evaluable),
        n_positive=int(y_true.sum()),
        confusion=cm,
        precision=float(precision),
        recall=float(recall),
        f1=float(f1),
        roc_auc=roc_auc,
        f1_ci=f1_ci,
        roc_auc_ci=auc_ci,
        n_abstentions=n_abstentions,
        roc_auc_committed=roc_auc_committed,
        n_committed=len(committed),
    )


def _bootstrap_cis(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_score: np.ndarray,
    *,
    n: int,
    seed: int,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Percentile bootstrap CIs for F1 and ROC-AUC.

    Resamples that end up single-class are skipped rather than scored, since both
    metrics are undefined there and substituting 0 or 0.5 would bias the interval.
    """
    if n <= 0 or len(y_true) < 2:
        return None, None

    rng = np.random.default_rng(seed)
    f1s: list[float] = []
    aucs: list[float] = []
    idx = np.arange(len(y_true))

    for _ in range(n):
        pick = rng.choice(idx, size=len(idx), replace=True)
        t, p, s = y_true[pick], y_pred[pick], y_score[pick]
        if len(np.unique(t)) < 2:
            continue
        _, _, f1, _ = precision_recall_fscore_support(
            t, p, labels=[LABEL_PD], average="binary", pos_label=LABEL_PD,
            zero_division=0.0,
        )
        f1s.append(float(f1))
        aucs.append(float(roc_auc_score(t, s)))

    def pct(values: list[float]) -> tuple[float, float] | None:
        if len(values) < 50:  # too few usable resamples for a credible interval
            return None
        return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))

    return pct(f1s), pct(aucs)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--pd-prevalence", type=float, default=0.05)
    parser.add_argument(
        "--missing-rate",
        type=float,
        default=0.1,
        help="fraction of records given NaN ground truth, to exercise the 3.3 path",
    )
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--clean", action="store_true", help="use the clean mock")
    parser.add_argument("--out", type=Path, default=None, help="write per-record CSV here")
    args = parser.parse_args(argv)

    df = add_random_labels(
        load(),
        seed=args.seed,
        pd_prevalence=args.pd_prevalence,
        missing_rate=args.missing_rate,
    )
    outcome = run_pipeline(df, messy=not args.clean)
    metrics = evaluate(outcome, bootstrap=args.bootstrap, seed=args.seed)

    print("=" * 68)
    print(f"Task 3.2 — evaluation over Oncology.csv   (seed={args.seed})")
    print("=" * 68)
    print()
    print("Parse / validation failures by type")
    print("-" * 68)
    print(outcome.tally.summary())
    print()
    print(metrics.render())
    print()
    print("=" * 68)
    print("Labels are RANDOM by instruction, so these metrics measure the")
    print("evaluation harness, not clinical accuracy.")
    print("=" * 68)

    if args.out:
        outcome.frame.to_csv(args.out, index=False)
        print(f"\nper-record results written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
