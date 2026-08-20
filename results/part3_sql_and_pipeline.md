# Part 3 — SQL & Python Pipeline

<!-- ---------------------------------------------------------------------------
COMMENTS TO CLAUDE

Mark feedback inline, next to whatever it refers to, in this form:

    > **@claude:** rewrite this, it repeats the point above

Use `@claude` and nothing else — a different marker will be missed by the sweep:

    grep -n '@claude' results/*.md

These HTML comment blocks do not render, so they stay out of the submitted PDF.
---------------------------------------------------------------------------- -->

---

## Task 3.1 — SQL

### Entity-relationship diagram

```mermaid
erDiagram
    patients {
        integer patient_id PK
        date    birth_date
        text    sex
    }
    visits {
        integer visit_id PK
        integer patient_id FK
        date    visit_date
        text    department
        integer provider_id
    }
    diagnoses {
        integer diagnosis_id PK
        integer visit_id FK
        text    icd10_code
        text    description
    }
    medications {
        integer med_id PK
        integer patient_id FK
        integer visit_id FK "nullable"
        text    drug_name
        date    start_date
        date    end_date
        numeric dose_mg
    }
    notes {
        integer note_id PK
        integer visit_id FK
        text    note_text
        timestamptz created_at
    }

    patients    ||--o{ visits      : "attends"
    patients    ||--o{ medications : "is prescribed"
    visits      ||--o{ diagnoses   : "records"
    visits      ||--o{ notes       : "documents"
    visits      |o--o{ medications : "ordered during"
```

DDL: [`sql/schema.sql`](../sql/schema.sql).

### Three things the diagram makes visible

**1. `medications` has two parents.** It carries both `patient_id` and `visit_id`, so it
hangs off `patients` directly *and* off `visits`. That is a deliberate denormalisation —
it lets a prescription exist without an encounter (a phone renewal, a transferred
medication list) by leaving `visit_id` NULL. It also creates a consistency hazard the
schema cannot enforce: nothing stops `medications.patient_id` disagreeing with
`visits.patient_id` for the same row. In production that wants either a composite foreign
key or a `CHECK` trigger. It is also what forces query 3's join key.

**2. Diagnoses and notes hang off the *visit*, not the patient.** So any patient-level
question about diagnoses has to travel `patients → visits → diagnoses`. A patient with no
visits therefore has no diagnoses by construction, and patient-level counts are only as
complete as the visit records.

**3. There is no encounter-level uniqueness on `notes`.** Nothing prevents several notes
per visit, which is exactly the duplication query 5 has to resolve. The absence of a
constraint is the reason the query is needed.

### The queries

| # | Question | File | The decision that changes the answer |
| --- | --- | --- | --- |
| 1 | Distinct patients with ≥1 Neurology visit in 2025 | [`01_…`](../sql/queries/01_neurology_patients_2025.sql) | Half-open date range; department matched exactly, since `ILIKE '%neurolog%'` also catches *Neurosurgery* |
| 2 | Each patient's first-ever visit date and its department | [`02_…`](../sql/queries/02_first_visit_per_patient.sql) | `LEFT JOIN` so patients with no visits survive; ties broken on `visit_id` for determinism |
| 3 | G20 patients never prescribed a levodopa-containing drug | [`03_…`](../sql/queries/03_parkinsons_without_levodopa.sql) | `LIKE 'G20%'` so the query is correct under both WHO ICD-10 (no G20 children) and ICD-10-CM FY2024 (which retired the bare code for G20.A1/A2, G20.B1/B2, G20.C); joined via `medications.patient_id` so prescriptions with a NULL `visit_id` still count |
| 4 | Average diagnoses per visit, by department, 2025 | [`04_…`](../sql/queries/04_avg_diagnoses_per_visit_2025.sql) | `LEFT JOIN` so zero-diagnosis visits stay in the denominator; `::numeric` so 3/2 is not 1 |
| 5 | Exactly one row per visit: the most recent note | [`05_…`](../sql/queries/05_latest_note_per_visit.sql) | Tie-break on `note_id`, because identical timestamps are the signature of the double-submit that created the duplicates |

Each file's header carries the full assumptions, the rejected alternatives and the reasoning —
one place to read, one place to change.

One item is repeated here rather than left in its file, because it changes how the *output*
should be read: **query 3 over-reports** — `ILIKE '%levodopa%'` misses brand names, so a treated
patient can appear untreated.

### Unit tests

[`tests/test_sql_queries.py`](../tests/test_sql_queries.py) — 24 tests against a real
PostgreSQL cluster, aimed at boundaries rather than happy paths, because that is where a
plausible-looking query is wrong: 31 December vs 1 January, a patient with no visits, a visit
with no diagnoses, a prescription with a NULL `visit_id`, same-day visit ties, identical note
timestamps, and `Neurosurgery` not matching `Neurology`.

Four pin a decision rather than check correctness, so it cannot drift silently:
integer division must not truncate; the levodopa over-report above is asserted as current
behaviour; and two guard query 2 — that its `DISTINCT ON` and `LATERAL` forms agree, and that
moving `LATERAL`'s correlation into the `ON` clause silently loses rows.

**How they run.** [`tests/conftest.py`](../tests/conftest.py) starts a throwaway cluster with
`initdb` in a temp directory, on a Unix socket only — no Docker, no port collisions, and no
pre-existing server required. Each test gets the schema applied inside a transaction that is
rolled back afterwards; since DDL is transactional in PostgreSQL, isolation is free. If the
PostgreSQL binaries are not on `PATH`, these tests **skip with a clear reason** rather than
failing.

```
uv run pytest tests/test_sql_queries.py -v
```

---

## Task 3.2 — Python evaluation pipeline

[`src/evaluate.py`](../src/evaluate.py) · run with `uv run python -m src.evaluate`
· tests: [`tests/test_evaluate.py`](../tests/test_evaluate.py) (21)

The property of the corpus that shaped this implementation: **62 of the 90 notes (69%) contain
no disease-status or progression vocabulary at all** — no "progressive disease", "PD", "stable
disease", "PR", "remission" or "no evidence of". They are consult letters, pre-operative notes
and procedure reports. So the abstention path is the common case here, not an edge case, and the
mock draws it for most notes accordingly.

### What the pipeline does

| Step | Function | Notes |
| --- | --- | --- |
| Random ground truth | `add_random_labels` | Seeded, fair coin, every record labelled — the literal reading of "a column of random binary labels". Prevalence and missing-label injection are keyword arguments for the tests, not CLI options, since neither is part of what 3.2 asks for. |
| Mock the model | `call_local_llm(text) -> dict` | The signature the assignment specifies. Deterministic per note. It simulates the *model*, so it emits the intermediate 0–100 contract; `verify_output` rescales to the 0.0–1.0 output schema (see 2.3). |
| Mock *messy* output | `call_local_llm_messy(text) -> str` | Fenced blocks, leading/trailing prose, truncation, invalid JSON, out-of-range confidence, unknown fields — drawn at fixed probabilities. |
| Parse and validate | `verify_output` (Part 2) | Reuses the Part-2 validator rather than reimplementing it. |
| Evaluate | `evaluate` | Confusion matrix, PD-class precision/recall/F1, ROC-AUC, bootstrap CIs, coverage. |

**Why there are two mocks.** A mock that only ever returns a clean dict cannot test the parser,
and robust parsing is explicitly assessed. `call_local_llm` satisfies the required signature;
the pipeline calls `call_local_llm_messy` so the failure paths genuinely execute and appear in
the tally. The mock also draws *real substrings* of each note as evidence quotes — an invented
quote would fail the grounding check for the wrong reason and tell us nothing.

### Two bugs found by running it

Both were real defects in this pipeline, caught by executing it rather than by reading it.

**1. Abstentions were being scored as near-certain PD.** `confidence_score` is confidence in
*whichever* label was chosen, so P(PD) for a Non-PD prediction is `1 − confidence`. But the D13
abstention signature is `Non-PD` with a **low** confidence, meaning "the note says nothing" —
which that formula turns into `1 − 0.1 = 0.9`, i.e. "almost certainly PD". With ~69% of the
corpus abstaining, this single sign error dominated the ranking and drove **ROC-AUC to 0.079
(95% CI [0.007, 0.177]) against random labels** — a value chance cannot produce, which is what
made it visible. Fixed by scoring an abstention as a constant `UNINFORMATIVE_SCORE = 0.5`, so
abstentions tie and contribute no discrimination in either direction. That is the honest
encoding of "no evidence".

**2. The pipeline was not reproducible.** The per-note seed was `abs(hash(text))`, and Python
salts string hashing per process (PEP 456) unless `PYTHONHASHSEED` is pinned — so the failure
tally changed between runs. Fixed with SHA-256. Worth recording because Part 2.6 argues at
length for reproducibility and this was exactly the hidden non-determinism it warns about,
sitting in our own code. Two consecutive runs now produce byte-identical output.

### Results (seed 20260819)

```
Parse / validation failures by type        Record accounting
  records: 90                                records in corpus                  90
  valid:   68                                excluded - parse/validation failed 22
  failed:  22                                excluded - no ground truth           0
    no_json_found:           11              evaluated                           68
    schema_validation_error:  7              of which PD (positive class)         37
    json_decode_error:        4              abstentions among valid outputs      48

Confusion matrix                           PD-class metrics
                pred Non-PD  pred PD        precision  0.833
  true Non-PD            30        1        recall     0.135
  true PD                32        5        f1         0.233  95% CI [0.056, 0.400]
                                            roc-auc    0.532  95% CI [0.424, 0.646]

Selective prediction (abstentions excluded)
  committed on 20 of 68 (29% coverage)   roc-auc 0.637
```

**These numbers measure the harness, not clinical accuracy** — the labels are random by
instruction, so no relationship to the predictions exists to be found. The output says so
explicitly, because a table of metrics with no such caveat invites exactly the
misinterpretation Q1.2f is about.

The number worth reading is **ROC-AUC 0.532, 95% CI [0.424, 0.646]** — an interval straddling
0.5. That is exactly the right answer: against labels with no relationship to the input, a
correct harness must find no discrimination, and the interval says so rather than leaving it to
be assumed. It is the strongest available evidence that the evaluation code is measuring what it
claims to. An AUC far from 0.5 here would have indicated a bug, which is how the abstention
sign error described above was originally caught.

Precision 0.833 against recall 0.135 is the other thing to notice, and it is an artefact worth
naming: the mock abstains on most notes, so it predicts PD rarely. Predicting the positive class
rarely makes precision look good and recall terrible — the threshold effect discussed in 3.3
below, visible here by construction rather than by argument.

## Task 3.3 — Two written questions

### Records with no ground truth came through your SQL. How does your evaluation function handle them, and why does it matter?

They are **excluded from every metric and counted separately in the printed report**.
`evaluate()` partitions the corpus three ways — parse/validation failures, records with a null
label, and records actually evaluated — and prints all three counts above the metrics.
Crucially the two exclusion reasons are reported *separately*, because they have different
owners: a parse failure is a model or parser defect, a missing label is a data problem, and
collapsing them into one "skipped" number hides which team needs to act.

Why it matters, in order of severity:

**Unlabelled records are not a random sample.** They are frequently unlabelled *because* they
were hard — the annotator could not decide, the record was ambiguous, or a join upstream lost
it. Dropping them silently therefore removes disproportionately difficult cases and inflates
every metric. The measured score drifts away from production performance in the optimistic
direction, which is the worst direction for a clinical system.

**Imputing them is worse than dropping them.** Filling a missing label with the majority class
manufactures ground truth. At the ~5% clinical prevalence of Q1.2c, defaulting the unlabelled to Non-PD inflates
accuracy and specificity while corrupting recall, and the corruption is invisible because the
fabricated labels look like data.

**An unreported denominator makes the metric unreadable.** `F1 = 0.92` over 1,000 records and
over 60 records are different claims. Without the exclusion counts a reader cannot tell which
they are looking at, cannot compute a confidence interval, and cannot notice that half the
corpus vanished.

**The missingness rate is itself a monitoring signal.** A rising proportion of unlabelled
records means annotation is falling behind or a SQL join is silently dropping rows — the
latter being the failure mode the question's phrasing hints at. That deserves an alert, not a
`dropna()`.

**Practically**, NaN labels must also never reach scikit-learn: depending on the metric they
either raise or coerce into nonsense. Handling them explicitly at the boundary is what keeps a
silent `except: pass` out of the pipeline.

### Your ROC-AUC is 0.94 but F1 for the PD class is 0.61. Explain how both can be true at once, and what you would do about it.

**They measure different things, and only one of them involves a decision.** ROC-AUC is
threshold-free: it is the probability that a randomly chosen positive is ranked above a
randomly chosen negative. It measures *ordering* and is insensitive to prevalence. F1 is
computed at **one specific threshold** and depends on precision, which is acutely
prevalence-sensitive. So 0.94 says the model ranks well; 0.61 says the decision rule applied to
that ranking is poor. Both can be true simultaneously, and at low prevalence they routinely are.

A concrete illustration. Take 1,000 records with 50 positives (5%). Excellent ranking, AUC 0.94.
Threshold at the default 0.5 and you might get 40 TP, 60 FP, 10 FN — precision 0.40, recall
0.80, F1 0.53. The 60 false positives come from the top tail of 950 negatives; because
negatives outnumber positives 19:1, even a small false-positive *rate* produces an absolute
count that swamps precision. ROC-AUC never sees this, because its x-axis is a *rate* over that
huge negative pool. This is the same mechanism as the ROC-AUC critique in Q1.2c.

**What I would do, cheapest and most likely first:**

1. **Move the threshold before touching the model.** Sweep it on validation data and choose
   against the clinical false-negative-to-false-positive cost ratio rather than leaving it at
   0.5. When AUC is 0.94, most of the F1 gap is usually recoverable here alone, and it costs
   nothing.
2. **Read the precision-recall curve, not the ROC.** At 5% prevalence the PR curve is the
   informative one; it shows directly whether *any* operating point achieves acceptable
   precision, or whether the ranking is good but the top of it is contaminated.
3. **Check calibration.** ROC-AUC is invariant under any monotone transform of the scores, so a
   model can rank perfectly and still be badly calibrated — and a badly calibrated score makes
   every threshold choice wrong. Reliability diagram, ECE, Brier; then Platt scaling, which
   changes the thresholded metrics without changing AUC at all.
4. **Consider selective prediction.** With AUC 0.94 there is almost certainly a high-precision
   region. Report precision at fixed recall and the risk-coverage curve, and route the
   uncertain middle band to clinician review. This trades coverage for precision deliberately
   instead of accepting a bad F1 at full coverage.
5. **Audit the positive labels.** With few positives, a handful of incorrect gold labels moves
   F1 substantially while barely touching AUC. Re-adjudicate the false positives and false
   negatives with a clinician before concluding the model is at fault.
6. **Report confidence intervals on both.** F1 over a small positive class has a wide interval;
   0.61 may not be statistically distinguishable from 0.75, in which case some of the "gap"
   is noise. The run above reports a CI on both metrics for exactly this reason.
7. **Only then change the model.** Threshold, calibration and label quality account for this
   pattern far more often than model capacity does, and all three are cheaper to fix.

This pipeline shows the pattern in miniature: committed-subset ROC-AUC of **0.637** against an
F1 of **0.233**, with precision 0.833 and recall 0.135. The driver is abstention — most records
carry no evidence, so the model commits rarely, which flatters precision and destroys recall
while the ranking over the committed subset stays better than any single decision rule applied
corpus-wide can express. (With random labels the magnitude is inside the confidence intervals;
the mechanism is the point.)
