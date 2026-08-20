"""Tests for the Task 3.1 SQL, run against a real PostgreSQL cluster.

Each test seeds the minimum rows needed to make one behaviour observable. The
interesting cases are the boundaries — visits on 31 December, patients with no
visits, visits with no diagnoses, ties on a sort key — because those are where a
plausible-looking query is wrong.
"""

from __future__ import annotations

import datetime as dt

import pytest

pytestmark = pytest.mark.sql


# --------------------------------------------------------------------------- #
# 3.1.1  Distinct patients with a Neurology visit in 2025
# --------------------------------------------------------------------------- #


@pytest.fixture
def neurology_data(seed):
    seed("patients", "patient_id, birth_date, sex", [(1, "1970-01-01", "F"), (2, "1980-01-01", "M"), (3, "1990-01-01", "F")])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department, provider_id",
        [
            (10, 1, "2025-03-01", "Neurology", 100),   # counts
            (11, 1, "2025-06-01", "Neurology", 100),   # same patient, must not double-count
            (12, 2, "2024-12-31", "Neurology", 100),   # wrong year
            (13, 2, "2026-01-01", "Neurology", 100),   # wrong year, boundary
            (14, 3, "2025-05-01", "Cardiology", 101),  # wrong department
            (15, 3, "2025-12-31", "Neurology", 100),   # last day of 2025, counts
        ],
    )


def test_counts_distinct_patients_not_visits(run_query, neurology_data):
    rows = run_query("01")
    assert rows == [{"neurology_patients_2025": 2}]


def test_year_boundaries_are_half_open(run_query, seed):
    seed("patients", "patient_id", [(1,), (2,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [(10, 1, "2025-12-31", "Neurology"), (11, 2, "2026-01-01", "Neurology")],
    )
    assert run_query("01") == [{"neurology_patients_2025": 1}]


def test_department_match_is_exact_not_prefix(run_query, seed):
    """'Neurosurgery' must not be counted as Neurology."""
    seed("patients", "patient_id", [(1,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [(10, 1, "2025-03-01", "Neurosurgery")],
    )
    assert run_query("01") == [{"neurology_patients_2025": 0}]


# --------------------------------------------------------------------------- #
# 3.1.2  First-ever visit per patient
# --------------------------------------------------------------------------- #


def test_returns_earliest_visit_and_its_department(run_query, seed):
    seed("patients", "patient_id", [(1,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [
            (10, 1, "2023-05-01", "Cardiology"),
            (11, 1, "2022-01-15", "Neurology"),  # earliest
            (12, 1, "2024-08-09", "Oncology"),
        ],
    )
    rows = run_query("02")
    assert rows == [
        {
            "patient_id": 1,
            "first_visit_date": dt.date(2022, 1, 15),
            "first_visit_department": "Neurology",
        }
    ]


def test_patient_with_no_visits_still_appears(run_query, seed):
    """'For every patient' is literal: a GROUP BY over visits would drop this row."""
    seed("patients", "patient_id", [(1,), (2,)])
    seed("visits", "visit_id, patient_id, visit_date, department", [(10, 1, "2025-01-01", "Neurology")])

    rows = run_query("02")
    assert len(rows) == 2
    visitless = next(r for r in rows if r["patient_id"] == 2)
    assert visitless["first_visit_date"] is None
    assert visitless["first_visit_department"] is None


def test_same_day_tie_is_broken_deterministically_by_visit_id(run_query, seed):
    seed("patients", "patient_id", [(1,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [(21, 1, "2025-02-02", "Oncology"), (20, 1, "2025-02-02", "Neurology")],
    )
    rows = run_query("02")
    assert rows[0]["first_visit_department"] == "Neurology"  # visit_id 20 wins


# --------------------------------------------------------------------------- #
# 3.1.3  Parkinson's without levodopa
# --------------------------------------------------------------------------- #


@pytest.fixture
def parkinsons_data(seed):
    seed("patients", "patient_id", [(1,), (2,), (3,), (4,), (5,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [
            (10, 1, "2025-01-01", "Neurology"),
            (11, 2, "2025-01-01", "Neurology"),
            (12, 3, "2025-01-01", "Neurology"),
            (13, 4, "2025-01-01", "Neurology"),
            (14, 5, "2025-01-01", "Neurology"),
        ],
    )
    seed(
        "diagnoses",
        "diagnosis_id, visit_id, icd10_code, description",
        [
            (20, 10, "G20", "Parkinson's disease"),
            (21, 11, "G20", "Parkinson's disease"),
            (22, 12, "G20.A1", "Parkinson's, subcode"),   # ICD-10-CM FY2024 subcode
            (23, 13, "G21", "Secondary parkinsonism"),    # not G20
            (24, 14, "G20", "Parkinson's disease"),
        ],
    )
    seed(
        "medications",
        "med_id, patient_id, visit_id, drug_name, dose_mg",
        [
            (30, 2, 11, "Carbidopa-Levodopa", 250),  # treated -> excluded
            (31, 5, None, "levodopa/benserazide", 100),  # NULL visit_id, still treated
            (32, 1, 10, "Amantadine", 100),  # unrelated drug, still untreated
        ],
    )


def test_finds_untreated_parkinsons_patients(run_query, parkinsons_data):
    rows = run_query("03")
    assert [r["patient_id"] for r in rows] == [1, 3]


def test_ilike_matches_combination_drug_names(run_query, parkinsons_data):
    """'Carbidopa-Levodopa' must count as levodopa exposure."""
    assert 2 not in [r["patient_id"] for r in run_query("03")]


def test_prescription_without_a_visit_still_counts_as_treated(run_query, parkinsons_data):
    """The join is on medications.patient_id, so a NULL visit_id does not hide it."""
    assert 5 not in [r["patient_id"] for r in run_query("03")]


def test_g20_subcodes_are_included(run_query, parkinsons_data):
    assert 3 in [r["patient_id"] for r in run_query("03")]


def test_non_g20_parkinsonism_is_excluded(run_query, parkinsons_data):
    assert 4 not in [r["patient_id"] for r in run_query("03")]


def test_known_limitation_brand_names_are_missed(run_query, seed):
    """Documented over-report: a patient on Sinemet looks untreated.

    Asserted deliberately. The limitation is stated in the query header, and
    pinning it means a future switch to terminology-based matching will fail this
    test and force the note to be updated rather than left stale.
    """
    seed("patients", "patient_id", [(1,)])
    seed("visits", "visit_id, patient_id, visit_date, department", [(10, 1, "2025-01-01", "Neurology")])
    seed("diagnoses", "diagnosis_id, visit_id, icd10_code", [(20, 10, "G20")])
    seed("medications", "med_id, patient_id, visit_id, drug_name", [(30, 1, 10, "Sinemet")])

    assert [r["patient_id"] for r in run_query("03")] == [1]


# --------------------------------------------------------------------------- #
# 3.1.4  Average diagnoses per visit, per department, 2025
# --------------------------------------------------------------------------- #


def test_visits_with_zero_diagnoses_are_in_the_denominator(run_query, seed):
    """The crux: an INNER JOIN would report 1.5 here instead of 1.0."""
    seed("patients", "patient_id", [(1,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [
            (10, 1, "2025-01-01", "Neurology"),
            (11, 1, "2025-02-01", "Neurology"),  # no diagnoses
        ],
    )
    seed(
        "diagnoses",
        "diagnosis_id, visit_id, icd10_code",
        [(20, 10, "G20"), (21, 10, "I10")],
    )

    rows = run_query("04")
    assert len(rows) == 1
    assert rows[0]["department"] == "Neurology"
    assert rows[0]["visits"] == 2
    assert rows[0]["diagnoses"] == 2
    assert float(rows[0]["avg_diagnoses_per_visit"]) == pytest.approx(1.0)


def test_averages_are_grouped_per_department(run_query, seed):
    seed("patients", "patient_id", [(1,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [
            (10, 1, "2025-01-01", "Neurology"),
            (11, 1, "2025-01-02", "Cardiology"),
            (12, 1, "2025-01-03", "Cardiology"),
        ],
    )
    seed(
        "diagnoses",
        "diagnosis_id, visit_id, icd10_code",
        [(20, 10, "G20"), (21, 11, "I10"), (22, 11, "I25"), (23, 12, "I48")],
    )

    by_dept = {r["department"]: float(r["avg_diagnoses_per_visit"]) for r in run_query("04")}
    assert by_dept == {"Cardiology": pytest.approx(1.5), "Neurology": pytest.approx(1.0)}


def test_visits_outside_2025_are_excluded(run_query, seed):
    seed("patients", "patient_id", [(1,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [(10, 1, "2024-06-01", "Neurology"), (11, 1, "2025-06-01", "Neurology")],
    )
    seed("diagnoses", "diagnosis_id, visit_id, icd10_code", [(20, 10, "G20"), (21, 10, "I10"), (22, 11, "G20")])

    rows = run_query("04")
    assert rows[0]["visits"] == 1
    assert float(rows[0]["avg_diagnoses_per_visit"]) == pytest.approx(1.0)


def test_integer_division_does_not_truncate(run_query, seed):
    """3 diagnoses over 2 visits is 1.5, not 1."""
    seed("patients", "patient_id", [(1,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [(10, 1, "2025-01-01", "Neurology"), (11, 1, "2025-01-02", "Neurology")],
    )
    seed(
        "diagnoses",
        "diagnosis_id, visit_id, icd10_code",
        [(20, 10, "A"), (21, 10, "B"), (22, 11, "C")],
    )
    assert float(run_query("04")[0]["avg_diagnoses_per_visit"]) == pytest.approx(1.5)


# --------------------------------------------------------------------------- #
# 3.1.5  Latest note per visit
# --------------------------------------------------------------------------- #


def test_returns_exactly_one_row_per_visit(run_query, seed):
    seed("patients", "patient_id", [(1,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [(10, 1, "2025-01-01", "Neurology"), (11, 1, "2025-02-01", "Neurology")],
    )
    seed(
        "notes",
        "note_id, visit_id, note_text, created_at",
        [
            (20, 10, "first draft", "2025-01-01 09:00+00"),
            (21, 10, "amended", "2025-01-01 17:30+00"),
            (22, 10, "middle", "2025-01-01 12:00+00"),
            (23, 11, "only note", "2025-02-01 08:00+00"),
        ],
    )

    rows = run_query("05")
    assert len(rows) == 2
    by_visit = {r["visit_id"]: r["note_text"] for r in rows}
    assert by_visit == {10: "amended", 11: "only note"}


def test_created_at_tie_is_broken_by_highest_note_id(run_query, seed):
    """Identical timestamps are the signature of a double-submit, so ties are likely."""
    seed("patients", "patient_id", [(1,)])
    seed("visits", "visit_id, patient_id, visit_date, department", [(10, 1, "2025-01-01", "Neurology")])
    seed(
        "notes",
        "note_id, visit_id, note_text, created_at",
        [
            (20, 10, "earlier insert", "2025-01-01 09:00+00"),
            (21, 10, "later insert", "2025-01-01 09:00+00"),
        ],
    )
    assert run_query("05")[0]["note_text"] == "later insert"


def test_visit_without_notes_is_absent(run_query, seed):
    seed("patients", "patient_id", [(1,)])
    seed(
        "visits",
        "visit_id, patient_id, visit_date, department",
        [(10, 1, "2025-01-01", "Neurology"), (11, 1, "2025-02-01", "Neurology")],
    )
    seed("notes", "note_id, visit_id, note_text, created_at", [(20, 10, "note", "2025-01-01 09:00+00")])

    assert [r["visit_id"] for r in run_query("05")] == [10]


def test_no_notes_at_all_returns_no_rows(run_query, seed):
    seed("patients", "patient_id", [(1,)])
    seed("visits", "visit_id, patient_id, visit_date, department", [(10, 1, "2025-01-01", "Neurology")])
    assert run_query("05") == []
