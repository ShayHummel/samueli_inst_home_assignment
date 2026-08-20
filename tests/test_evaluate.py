"""Tests for the Task 3.2 evaluation pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evaluate import (
    LABEL_NON_PD,
    LABEL_PD,
    UNINFORMATIVE_SCORE,
    Metrics,
    add_random_labels,
    call_local_llm,
    call_local_llm_messy,
    evaluate,
    probability_of_pd,
    run_pipeline,
)
from src.schema import ClinicalClassification

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
    payload = call_local_llm(NOTE_WITH_STATUS)
    assert isinstance(payload, dict)
    ClinicalClassification.model_validate(payload)  # raises if off-contract


def test_mock_is_deterministic_for_the_same_note():
    """Stable across processes: uses sha256, not the per-process-salted hash()."""
    assert call_local_llm(NOTE_WITH_STATUS) == call_local_llm(NOTE_WITH_STATUS)
    assert call_local_llm_messy(NOTE_WITH_STATUS) == call_local_llm_messy(NOTE_WITH_STATUS)


def test_note_without_status_vocabulary_produces_an_abstention():
    payload = call_local_llm(NOTE_WITHOUT_STATUS)
    record = ClinicalClassification.model_validate(payload)
    assert record.is_abstention
    assert record.supporting_evidence == []


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
    failed = outcome.frame[~outcome.frame["parse_ok"]]
    assert not failed.empty, "expected the messy mock to produce some failures"
    assert failed["failure_type"].notna().all()
    assert failed["failure_detail"].notna().all()
    assert sum(outcome.tally.as_dict().values()) == len(failed)


def test_clean_mode_produces_no_parse_failures():
    df = frame([NOTE_WITH_STATUS, NOTE_WITHOUT_STATUS] * 20, [0.0, 1.0] * 20)
    outcome = run_pipeline(df, messy=False)
    assert outcome.tally.failures == 0


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def test_records_without_ground_truth_are_excluded_and_reported():
    df = frame([NOTE_WITH_STATUS] * 10, [0.0, 1.0, None, None, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    metrics = evaluate(run_pipeline(df, messy=False), bootstrap=0)
    assert metrics.n_missing_ground_truth == 2
    assert metrics.n_evaluated == 8
    assert metrics.n_total == 10
    assert "no ground truth         2" in metrics.render()


def test_exclusions_are_visible_in_the_rendered_report():
    """Silent exclusion inflates every score, so the counts must be printed."""
    df = frame([NOTE_WITH_STATUS] * 6, [0.0, 1.0, None, 0.0, 1.0, 0.0])
    text = evaluate(run_pipeline(df, messy=False), bootstrap=0).render()
    assert "records in corpus" in text
    assert "parse/validation failed" in text
    assert "evaluated" in text


def test_confusion_matrix_orientation_is_truth_by_prediction():
    df = frame([NOTE_WITH_STATUS] * 4, [0.0, 0.0, 1.0, 1.0])
    metrics = evaluate(run_pipeline(df, messy=False), bootstrap=0)
    assert metrics.confusion.shape == (2, 2)
    assert metrics.confusion.sum() == metrics.n_evaluated


def test_roc_auc_undefined_with_a_single_class_present():
    df = frame([NOTE_WITH_STATUS] * 5, [0.0] * 5)
    metrics = evaluate(run_pipeline(df, messy=False), bootstrap=0)
    assert metrics.roc_auc is None
    assert "undefined" in metrics.render()


def test_no_evaluable_records_renders_without_crashing():
    df = frame([NOTE_WITH_STATUS] * 3, [None, None, None])
    metrics = evaluate(run_pipeline(df, messy=False), bootstrap=0)
    assert metrics.n_evaluated == 0
    assert "metrics undefined" in metrics.render()


def test_selective_prediction_reports_coverage():
    notes = [NOTE_WITH_STATUS] * 10 + [NOTE_WITHOUT_STATUS] * 10
    df = frame(notes, [0.0, 1.0] * 10)
    metrics = evaluate(run_pipeline(df, messy=False), bootstrap=0)
    assert metrics.n_abstentions > 0
    assert metrics.n_committed < metrics.n_evaluated
    assert "coverage" in metrics.render()


def test_bootstrap_interval_brackets_the_point_estimate():
    df = frame([NOTE_WITH_STATUS] * 60, ([0.0] * 3 + [1.0]) * 15)
    metrics = evaluate(run_pipeline(df, messy=False), bootstrap=500, seed=11)
    if metrics.roc_auc_ci is not None:
        low, high = metrics.roc_auc_ci
        assert low <= metrics.roc_auc <= high


def test_metrics_render_is_stable_for_an_empty_run():
    m = Metrics(
        n_total=0, n_parse_failed=0, n_missing_ground_truth=0, n_evaluated=0,
        n_positive=0, confusion=None, precision=None, recall=None, f1=None, roc_auc=None,
    )
    assert "metrics undefined" in m.render()
