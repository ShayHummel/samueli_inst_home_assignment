"""Tests for the Task 3.2 evaluation pipeline."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.evaluate import (
    LABEL_NON_PD,
    LABEL_PD,
    UNINFORMATIVE_SCORE,
    add_random_labels,
    call_local_llm,
    call_local_llm_messy,
    evaluate,
    mock_stage1,
    mock_stage2_responses,
    probability_of_pd,
    run_pipeline,
)
from src.schema import ClinicalClassification, RawClassification

NOTE_WITH_STATUS = (
    "IMPRESSION: Restaging CT demonstrates no evidence of progression. The patient "
    "remains on the current regimen and is tolerating it well."
)
NOTE_WITHOUT_STATUS = (
    "PREOPERATIVE DIAGNOSIS: Right inguinal hernia. PROCEDURE: Open repair with mesh. "
    "ESTIMATED BLOOD LOSS: Minimal. The patient tolerated the procedure well."
)


def frame(notes: list[str], truths: list[float | None]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_row_id": list(range(len(notes))),
            "transcription": notes,
            "ground_truth": [np.nan if t is None else t for t in truths],
        }
    )


# --------------------------------------------------------------------------- #
# Random labels
# --------------------------------------------------------------------------- #


def test_labels_are_reproducible_for_a_seed():
    df = pd.DataFrame({"transcription": ["a"] * 200})
    a = add_random_labels(df, seed=7)["ground_truth"].tolist()
    b = add_random_labels(df, seed=7)["ground_truth"].tolist()
    assert a == b


def test_labels_differ_across_seeds():
    df = pd.DataFrame({"transcription": ["a"] * 200})
    a = add_random_labels(df, seed=1)["ground_truth"].tolist()
    b = add_random_labels(df, seed=2)["ground_truth"].tolist()
    assert a != b


def test_labels_are_binary_and_respect_prevalence():
    df = pd.DataFrame({"transcription": ["a"] * 4000})
    labels = add_random_labels(df, seed=3, pd_prevalence=0.05)["ground_truth"]
    assert set(labels.unique()) <= {0.0, 1.0}
    assert labels.mean() == pytest.approx(0.05, abs=0.02)


def test_missing_rate_injects_nan_ground_truth():
    df = pd.DataFrame({"transcription": ["a"] * 1000})
    labels = add_random_labels(df, seed=4, missing_rate=0.2)["ground_truth"]
    assert labels.isna().mean() == pytest.approx(0.2, abs=0.05)


# --------------------------------------------------------------------------- #
# Mock LLM
# --------------------------------------------------------------------------- #


def test_call_local_llm_returns_a_schema_valid_dict():
    """The mock simulates the *model*, so it speaks the intermediate 0-100 contract."""
    payload = call_local_llm(NOTE_WITH_STATUS)
    assert isinstance(payload, dict)
    raw = RawClassification.model_validate(payload)  # raises if off-contract
    # ...and must convert cleanly to the assignment's 0.0-1.0 output contract.
    out = raw.to_output()
    assert 0.0 <= out.confidence_score <= 1.0
    ClinicalClassification.model_validate(out.model_dump())


def test_mock_is_deterministic_for_the_same_note():
    """Stable across processes: uses sha256, not the per-process-salted hash()."""
    assert call_local_llm(NOTE_WITH_STATUS) == call_local_llm(NOTE_WITH_STATUS)
    assert call_local_llm_messy(NOTE_WITH_STATUS) == call_local_llm_messy(NOTE_WITH_STATUS)


def test_note_without_status_vocabulary_produces_an_abstention():
    payload = call_local_llm(NOTE_WITHOUT_STATUS)
    raw = RawClassification.model_validate(payload)
    assert raw.is_abstention, "abstention must be recognized on the 0-100 scale"
    assert raw.to_output().is_abstention, "and survive the rescale to 0.0-1.0"
    assert raw.supporting_evidence == []


def test_evidence_quotes_are_real_substrings_of_the_note():
    """A mock that invented quotes would fail grounding for the wrong reason."""
    payload = call_local_llm(NOTE_WITH_STATUS)
    for quote in payload["supporting_evidence"]:
        assert quote in NOTE_WITH_STATUS


def test_messy_mock_produces_more_than_one_shape():
    notes = [f"no evidence of progression, case {i}" for i in range(200)]
    outputs = [call_local_llm_messy(n) for n in notes]
    assert any(o.startswith("```") for o in outputs), "no fenced output produced"
    assert any("Certainly" in o for o in outputs), "no prose-wrapped output produced"
    assert any(not o.rstrip().endswith("}") for o in outputs), "no truncated output produced"


# --------------------------------------------------------------------------- #
# Confidence -> P(PD)
# --------------------------------------------------------------------------- #


def test_pd_confidence_maps_directly():
    """Input is already on the output scale — the rescale happened in to_output."""
    assert probability_of_pd(LABEL_PD, 0.9) == pytest.approx(0.9)


def test_non_pd_confidence_is_inverted():
    assert probability_of_pd(LABEL_NON_PD, 0.9) == pytest.approx(0.1)


def test_abstention_is_scored_as_uninformative():
    """The bug this guards: 1 - 0.1 = 0.9 would score "no information" as "likely PD"."""
    naive = 1.0 - 0.1
    actual = probability_of_pd(LABEL_NON_PD, 0.1, is_abstention=True)
    assert actual == pytest.approx(UNINFORMATIVE_SCORE)
    assert actual != pytest.approx(naive)


# --------------------------------------------------------------------------- #
# Running the corpus
# --------------------------------------------------------------------------- #


def test_pipeline_never_raises_and_tallies_every_record():
    df = frame([NOTE_WITH_STATUS, NOTE_WITHOUT_STATUS] * 15, [0.0, 1.0] * 15)
    outcome = run_pipeline(df)
    assert len(outcome.frame) == 30
    assert outcome.tally.total == 30
    assert outcome.tally.successes + outcome.tally.failures == 30


def test_failures_are_attributed_to_a_type_never_swallowed():
    df = frame([f"no evidence of progression case {i}" for i in range(120)], [0.0] * 120)
    outcome = run_pipeline(df)
    failed = outcome.frame[~outcome.frame["ok"]]
    assert not failed.empty, "expected the messy mock to produce some failures"
    assert failed["failure_type"].notna().all()
    assert failed["failure_detail"].notna().all()
    assert sum(outcome.tally.as_dict().values()) == len(failed)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def test_record_accounting_adds_up():
    """Every record lands in exactly one bucket, so the three must sum to the total.

    Asserted as an invariant rather than as fixed counts: stage 2 is always the messy
    mock, so which records fail is a property of the corpus, and a record that fails
    the pipeline never reaches the missing-ground-truth bucket.
    """
    labels = [0.0, 1.0, None] * 15
    report = evaluate(run_pipeline(frame([f"case {i}" for i in range(45)], labels)))

    def value(label: str) -> int:
        line = next(ln for ln in report.splitlines() if label in ln)
        return int(line.split()[-1])

    assert (
        value("excluded - pipeline failed")
        + value("excluded - no ground truth")
        + value("evaluated")
        == value("records in corpus")
        == 45
    )


def test_records_without_ground_truth_are_excluded():
    """A NaN label must never reach the metrics."""
    labels = [None] * 20
    report = evaluate(run_pipeline(frame([f"case {i}" for i in range(20)], labels)))
    assert "evaluated                    0" in report
    assert "metrics undefined" in report


def test_exclusions_are_visible_in_the_report():
    """Silent exclusion inflates every score, so the counts must be printed."""
    report = evaluate(run_pipeline(frame([NOTE_WITH_STATUS] * 6, [0.0, 1.0, None, 0.0, 1.0, 0.0])))
    for label in ("records in corpus", "excluded - pipeline failed",
                  "excluded - no ground truth", "evaluated"):
        assert label in report


def test_report_contains_the_metrics_3_2_asks_for():
    notes = [f"no evidence of progression, case {i}" for i in range(40)]
    report = evaluate(run_pipeline(frame(notes, [0.0, 1.0] * 20)))
    assert "Confusion matrix" in report
    assert "true Non-PD" in report and "true PD" in report
    for metric in ("precision", "recall", "f1", "roc-auc"):
        assert metric in report


def test_roc_auc_undefined_with_a_single_class_present():
    """Undefined is the honest answer; 0.5 would be a fabricated number."""
    notes = [f"no evidence of progression, case {i}" for i in range(20)]
    assert "roc-auc    undefined" in evaluate(run_pipeline(frame(notes, [0.0] * 20)))


def test_abstentions_and_repairs_are_reported():
    notes = [NOTE_WITH_STATUS] * 10 + [NOTE_WITHOUT_STATUS] * 10
    report = evaluate(run_pipeline(frame(notes, [0.0, 1.0] * 10)))
    assert "abstentions" in report
    assert "recovered by stage-4 repair" in report


# --------------------------------------------------------------------------- #
# The evaluation must exercise the shipped pipeline, not a lookalike
# --------------------------------------------------------------------------- #


def test_run_pipeline_exercises_the_repair_stage():
    """3.2 evaluates `classify_note`, so stage 4 must actually run.

    An earlier version called `verify_output` directly, which skipped the
    stage-1/stage-2 split, the verdict-preservation check and the repair loop —
    measuring a lookalike of the shipped flow and overstating the failure rate.
    """
    notes = [f"no evidence of progression, case {i}" for i in range(120)]
    outcome = run_pipeline(frame(notes, [0.0] * 120))

    recovered = outcome.frame[(outcome.frame["repair_attempts"] > 0) & outcome.frame["ok"]]
    assert not recovered.empty, "no record was rescued by repair — stage 4 is not running"
    assert outcome.tally.failures > 0, "some notes must remain failed, or the tally is vacuous"


def test_repair_disabled_raises_the_failure_count():
    """Direct evidence that the recovered records really are repair's doing."""
    df = frame([f"no evidence of progression, case {i}" for i in range(120)], [0.0] * 120)
    with_repair = run_pipeline(df, max_repair_attempts=2).tally.failures
    without = run_pipeline(df, max_repair_attempts=0).tally.failures
    assert without > with_repair


def test_stage_one_and_stage_two_mocks_agree_so_drift_never_fires():
    """A mock whose stages disagreed would report verdict drift on every record."""
    from src.validation import FailureType

    outcome = run_pipeline(frame([NOTE_WITH_STATUS, NOTE_WITHOUT_STATUS] * 20, [0.0, 1.0] * 20))
    assert outcome.tally.as_dict()[FailureType.VERDICT_DRIFT.value] == 0


# --------------------------------------------------------------------------- #
# The two per-stage mocks
# --------------------------------------------------------------------------- #


def test_stage1_mock_emits_the_four_line_contract():
    text = mock_stage1(NOTE_WITH_STATUS)
    for line in ("VERDICT:", "CONFIDENCE:", "EVIDENCE:", "REASONING:"):
        assert line in text
    assert "{" not in text, "stage 1 must not emit JSON"


def test_stage1_mock_agrees_with_call_local_llm():
    """The two stages are built from one payload, so they cannot disagree."""
    payload = call_local_llm(NOTE_WITH_STATUS)
    assert f"VERDICT: {payload['classification']}" in mock_stage1(NOTE_WITH_STATUS)


def test_stage2_mock_queues_a_first_attempt_and_a_repair_response():
    first, repair = mock_stage2_responses(NOTE_WITH_STATUS)
    assert first == call_local_llm_messy(NOTE_WITH_STATUS)
    # Either the repair lands (clean JSON) or the model repeats itself verbatim.
    assert repair == first or json.loads(repair)


def test_stage2_mock_is_deterministic():
    assert mock_stage2_responses(NOTE_WITH_STATUS) == mock_stage2_responses(NOTE_WITH_STATUS)
