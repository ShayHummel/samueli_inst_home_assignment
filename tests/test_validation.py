"""Tests for the stage-3 output verifier."""

from __future__ import annotations

import pytest

from src.prompts import JSON_CONTRACT
from src.schema import (
    ABSTENTION_CONFIDENCE_CEILING,
    SCHEMA_FIELD_NAMES,
    Classification,
    ClinicalClassification,
)
from src.validation import (
    FailureTally,
    FailureType,
    extract_json_block,
    find_ungrounded_quotes,
    normalise_for_matching,
    parse_stage1_verdict,
    verify_output,
)

NOTE = (
    "REASON FOR CONSULTATION: Restaging CT. IMPRESSION: New hepatic lesions and "
    "enlargement of the retroperitoneal nodes, consistent with progressive disease. "
    "The patient's mother had progressive disease. If the patient progresses further, "
    "we will switch to second line."
)

VALID_JSON = """{
  "classification": "PD",
  "confidence_score": 91,
  "supporting_evidence": ["New hepatic lesions and enlargement of the retroperitoneal nodes"],
  "clinical_reasoning": "Imaging documents new and enlarging lesions."
}"""


# --------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------- #


def test_extracts_bare_object():
    assert extract_json_block(VALID_JSON) is not None


def test_extracts_from_markdown_fence():
    raw = f"```json\n{VALID_JSON}\n```"
    assert extract_json_block(raw) == VALID_JSON


def test_extracts_despite_trailing_prose():
    raw = f"Sure! Here is the JSON:\n{VALID_JSON}\nLet me know if you need anything else."
    block = extract_json_block(raw)
    assert block is not None and block.endswith("}")


def test_trailing_brace_in_prose_does_not_extend_the_object():
    """Brace matching, not a greedy regex — prose braces must not be swallowed."""
    raw = f"{VALID_JSON}\nNote: see section {{4}} for details."
    block = extract_json_block(raw)
    assert block is not None
    assert "section" not in block


def test_truncated_object_is_not_extracted():
    assert extract_json_block('{"classification": "PD", "confidence') is None


@pytest.mark.parametrize("raw", ["", "   ", "no json here at all"])
def test_no_json_returns_none(raw):
    assert extract_json_block(raw) is None


# --------------------------------------------------------------------------- #
# Normalisation and grounding
# --------------------------------------------------------------------------- #


def test_normalisation_folds_whitespace_case_and_smart_punctuation():
    assert normalise_for_matching("The  patient’s\nCT") == "the patient's ct"


def test_normalisation_does_not_strip_punctuation():
    """Stripping punctuation would let a negation match its own opposite."""
    assert "no" in normalise_for_matching("no evidence of progression")
    assert normalise_for_matching("no progression") != normalise_for_matching("progression")


def test_quote_grounded_despite_rewrapping():
    quote = "New hepatic lesions and enlargement\n  of the retroperitoneal nodes"
    assert find_ungrounded_quotes([quote], NOTE) == ()


def test_fabricated_quote_is_detected():
    ungrounded = find_ungrounded_quotes(["biopsy-confirmed progression of the primary"], NOTE)
    assert len(ungrounded) == 1


# --------------------------------------------------------------------------- #
# Schema rules
# --------------------------------------------------------------------------- #


def test_valid_output_passes():
    report = verify_output(VALID_JSON, NOTE, Classification.PD)
    assert report
    assert report.result is not None
    assert report.result.classification is Classification.PD


def test_confidence_out_of_range_is_a_schema_failure():
    """Confidence is on a 0-100 scale, so 140 is out of range."""
    bad = VALID_JSON.replace("91", "140")
    report = verify_output(bad, NOTE, Classification.PD)
    assert not report
    assert report.failure_type is FailureType.SCHEMA_VALIDATION_ERROR


def test_pd_without_evidence_is_rejected():
    """Asserting progression while quoting nothing is fabrication by construction."""
    with pytest.raises(ValueError, match="requires at least one supporting_evidence"):
        ClinicalClassification(
            classification=Classification.PD,
            confidence_score=0.8,
            supporting_evidence=[],
            clinical_reasoning="It looks like progression.",
        )


def test_unknown_field_is_rejected():
    bad = VALID_JSON.replace('"classification"', '"severity": "high", "classification"')
    report = verify_output(bad, NOTE, Classification.PD)
    assert not report
    assert report.failure_type is FailureType.SCHEMA_VALIDATION_ERROR


def test_non_object_json_is_reported_distinctly():
    report = verify_output("[1, 2, 3]", NOTE)
    assert not report
    # A bare array has no '{' at all, so extraction fails before type checking.
    assert report.failure_type is FailureType.NO_JSON_FOUND


def test_malformed_json_is_reported_as_decode_error():
    report = verify_output('{"classification": "PD",, "confidence_score": 0.5}', NOTE)
    assert not report
    assert report.failure_type is FailureType.JSON_DECODE_ERROR


# --------------------------------------------------------------------------- #
# Semantic checks a schema cannot express
# --------------------------------------------------------------------------- #


def test_verdict_drift_is_caught():
    """Stage 2 formats; it must never change the clinical conclusion."""
    report = verify_output(VALID_JSON, NOTE, Classification.NON_PD)
    assert not report
    assert report.failure_type is FailureType.VERDICT_DRIFT
    assert "must not change" in report.failure_detail


def test_drift_check_skipped_when_no_stage1_verdict_given():
    assert verify_output(VALID_JSON, NOTE, None)


def test_ungrounded_evidence_is_caught():
    bad = VALID_JSON.replace(
        "New hepatic lesions and enlargement of the retroperitoneal nodes",
        "widespread osseous metastases on bone scan",
    )
    report = verify_output(bad, NOTE, Classification.PD)
    assert not report
    assert report.failure_type is FailureType.EVIDENCE_NOT_IN_SOURCE
    assert report.ungrounded_quotes == ("widespread osseous metastases on bone scan",)


# --------------------------------------------------------------------------- #
# D13 abstention signature
# --------------------------------------------------------------------------- #


def test_abstention_signature_is_recognised():
    record = ClinicalClassification(
        classification=Classification.NON_PD,
        confidence_score=ABSTENTION_CONFIDENCE_CEILING,
        supporting_evidence=[],
        clinical_reasoning="The summary contains no assessable statement about disease status.",
    )
    assert record.is_abstention


def test_confident_non_pd_is_not_an_abstention():
    record = ClinicalClassification(
        classification=Classification.NON_PD,
        confidence_score=0.95,
        supporting_evidence=["no evidence of progression"],
        clinical_reasoning="Explicit denial of progression.",
    )
    assert not record.is_abstention


# --------------------------------------------------------------------------- #
# Stage 1 tail parsing
# --------------------------------------------------------------------------- #


STAGE1_TAIL = """1. LOCATE. ...prose...
6. DECIDE. The current status is stable disease.

VERDICT: Non-PD
CONFIDENCE: 88
EVIDENCE: "stable disease (SD)" | "no new lesions"
REASONING: Current status is SD; the 2023 PD is historical."""


def test_stage1_tail_parses():
    v = parse_stage1_verdict(STAGE1_TAIL)
    assert v is not None
    assert v.classification is Classification.NON_PD
    assert v.confidence == pytest.approx(88.0)
    assert v.evidence == ("stable disease (SD)", "no new lesions")
    assert "historical" in v.reasoning


def test_stage1_evidence_none_yields_empty_tuple():
    v = parse_stage1_verdict("VERDICT: Non-PD\nCONFIDENCE: 10\nEVIDENCE: NONE\nREASONING: nothing.")
    assert v is not None and v.evidence == ()


def test_stage1_missing_verdict_returns_none():
    assert parse_stage1_verdict("I think this is progression, probably.") is None


def test_stage1_confidence_is_clamped():
    v = parse_stage1_verdict("VERDICT: PD\nCONFIDENCE: 420\nEVIDENCE: NONE\nREASONING: x")
    assert v is not None and v.confidence == 100.0


def test_stage1_last_block_wins_when_restated():
    text = STAGE1_TAIL + "\n\nVERDICT: PD\nCONFIDENCE: 70\nEVIDENCE: NONE\nREASONING: revised."
    v = parse_stage1_verdict(text)
    assert v is not None and v.classification is Classification.PD


# --------------------------------------------------------------------------- #
# Failure accounting
# --------------------------------------------------------------------------- #


def test_tally_counts_by_type():
    tally = FailureTally()
    tally.record(verify_output(VALID_JSON, NOTE, Classification.PD))
    tally.record(verify_output(VALID_JSON, NOTE, Classification.NON_PD))
    tally.record(verify_output("garbage", NOTE))
    tally.record(verify_output("also garbage", NOTE))

    assert tally.total == 4
    assert tally.successes == 1
    assert tally.failures == 3
    assert tally.as_dict()[FailureType.VERDICT_DRIFT.value] == 1
    assert tally.as_dict()[FailureType.NO_JSON_FOUND.value] == 2
    assert "verdict_drift: 1" in tally.summary()


# --------------------------------------------------------------------------- #
# Prompt / schema drift
# --------------------------------------------------------------------------- #


def test_prompt_schema_block_matches_the_pydantic_model():
    """The prose contract in the prompts must not drift from the model."""
    for name in SCHEMA_FIELD_NAMES:
        assert f'"{name}"' in JSON_CONTRACT, f"{name} missing from the prompt schema block"
    assert len(SCHEMA_FIELD_NAMES) == JSON_CONTRACT.count('":')
