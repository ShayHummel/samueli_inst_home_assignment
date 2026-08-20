# EDA — `Oncology.csv`

Script: [`src/eda.py`](../src/eda.py) · reproduce with `uv run python -m src.eda`

## Shape

90 rows × 5 columns (`source_row_id`, `description`, `medical_specialty`, `sample_name`,
`transcription`). **No nulls, no duplicate transcriptions, 90 distinct `sample_name`s, and a
single `medical_specialty`** (`Hematology - Oncology`) — so specialty carries no signal and
cannot be used as a feature or a stratifier. Every text column is space-padded in the export
and needs stripping. `transcription` is the pipeline input.

Length is comfortable: median 332 words (~432 tokens), max 1,559 words (~2,026 tokens). **No
note exceeds 2,000 words**, so no chunking or long-context strategy is required — any of the
Part 1 candidate models handles these whole.

## The finding that shapes the task

| | notes | share |
|---|---:|---:|
| Contains **any** disease-status or progression token | 28 | **31.1%** |
| Contains **none** — must abstain under D13 | 62 | **68.9%** |

**Roughly two-thirds of this corpus cannot be classified PD or Non-PD on its content.** These
are consult letters, pre-operative notes and procedure reports that never state a response
status. This is the single most consequential number here, and it validates the D13 decision
directly: a pipeline that defaults silently to `Non-PD` would report ~62 confident negatives
it has no evidence for. The abstention signature (empty evidence + low confidence) is what
keeps those honest.

Splitting the 28 further: **9 notes carry PD-side vocabulary only, 13 Non-PD-side only, and
6 carry both** — and those 6 are exactly the temporality/negation cases where a keyword
matcher fails.

## Vocabulary is sparse and skewed to Non-PD

The literal RECIST tokens the prompt is built around are almost absent: **zero occurrences of
"progressive disease", zero of a standalone "PD", and only 2 of "progression"**. Non-PD
evidence is more common — "no evidence of" appears in 12 notes (13.3%), remission in 4,
"PR" in 3, "stable disease" in 1.

Two consequences. First, real PD prevalence in this corpus is very low, so the ~5% positive
class in Q1.2c is a realistic figure rather than a hypothetical. Second, a classifier keyed on
explicit RECIST abbreviations would find almost nothing; PD here must be inferred from
descriptive findings ("new lesions", metastatic spread — 14 notes mention metastasis).

## Which Part-2 traps are real here

| Trap | notes | share | Verdict |
|---|---:|---:|---|
| Historical timepoint (`previously`, `in 20XX`, `history of`, `s/p`) | 59 | **65.6%** | Dominant risk |
| Family-history subject (`mother`, `father`, `family history`, …) | 33 | **36.7%** | Very common |
| Hedged (`rule out`, `cannot exclude`, `concern for`, `suspicious for`) | 20 | 22.2% | Common |
| Negated progression | 0 | 0.0% | Not in this corpus |
| Hypothetical progression (`if … progresses`) | 0 | 0.0% | Not in this corpus |

This reorders the prompt's priorities against what the assignment's trap list implies. **Steps
2 (SUBJECT) and 4 (TIMEPOINT) of the reading procedure are doing the heavy lifting on real
data** — over a third of notes discuss a relative's disease, and two thirds contain historical
markers. The negation and hypothetical traps, by contrast, do not occur naturally here; they
remain worth defending against, but as synthetic regression cases rather than observed
frequencies.

## Data-quality notes

De-identification leaves visible artefacts: redacted clinician names (`Dr. X`) in 25 notes
(27.8%), placeholder tokens (`ABCD`, `XYZ`) in 10, and blanked spans (`____`) in 4. These are
harmless for classification but must not be quoted as supporting evidence, and a blanked span
can remove the very clause a decision would rest on.

Structure is heterogeneous: 159 distinct ALL-CAPS section headers across 90 notes, with the
most common (`HISTORY OF PRESENT ILLNESS`) in only 40. **There is no reliable section to
target**, so the pipeline must read whole notes rather than extracting a canonical
"Impression" block — and note that `FAMILY HISTORY` appears in 28 notes, which is precisely
where the subject trap lives.

## Implications for Task 3.2

1. **Labels are random by instruction**, so reported metrics measure the *evaluation harness*,
   not clinical accuracy. The report must say so plainly.
2. **n = 90 with ~5% true prevalence** means metric confidence intervals are very wide. Point
   estimates alone would be misleading; the Q1.2f "small test set" caution applies to our own
   evaluation here.
3. **Expect a high abstention rate (~69%)** from any faithful implementation. That is a
   correct result, not a bug.
4. **No chunking needed**; no stratification by specialty is possible.
