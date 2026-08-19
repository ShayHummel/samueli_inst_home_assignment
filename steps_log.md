# Steps Log

Working log for the Samueli Institute home assignment (NLP Research Scientist —
Clinical Text & LLMs). Every working session appends an entry here.

**Format choice:** Markdown rather than JSON. The assignment is explicitly graded
on *judgment and reasoning*, not just artefacts ("A well-argued partial solution
scores higher than an exhaustive but unreasoned one"). A log needs to carry
narrative rationale — why an approach was chosen and what was rejected — which
JSON records badly. Markdown also renders directly on GitHub for the reviewer.

Conventions:
- Newest entry at the bottom.
- Each entry: date, part of the assignment, what was done, decisions + rationale,
  artefacts produced, open questions.
- AI assistance is disclosed per the assignment's Logistics section ("you may use
  AI coding assistants — tell us where you did").

---

## 2026-08-19 — Session 1: Setup & orientation

**Part:** Repo setup + Part 1 scaffold.

### Done
- Read the assignment PDF (`hw_docs/Samueli_Home_Assignment_NLP_Research_Scientist -candidate.pdf`,
  5 pages) and mapped it to four parts:
  - **Part 1** — Architecture & Validation (theoretical: Q1.1 model selection, Q1.2 a–f validation).
  - **Part 2** — Clinical requirement → prompt (2.1–2.7: PD vs Non-PD classification).
  - **Part 3** — SQL (3.1, five Postgres queries) + Python eval pipeline (3.2) + two written questions (3.3).
  - **Part 4** — Embeddings & vector search (E.1–E.3).
- Inspected `hw_docs/Oncology.csv`: 90 data rows, 5 columns
  (`<unnamed index>`, `description`, `medical_specialty`, `sample_name`, `transcription`).
  `transcription` is the free-text clinical note and is the input to the Part-3 pipeline.
- Initialised the project: `uv` + `pyproject.toml`, Python pinned to 3.13,
  `src/` for code, `results/` for written answers, `tests/` for unit tests.

### Decisions + rationale
- **`uv` with per-part optional dependency groups** (`part2`, `part3`) instead of one
  flat dependency list, so a reviewer can see exactly what each part requires and
  install only that.
- **Python 3.13, not 3.14.** 3.14 is installed locally but pandas/scikit-learn wheel
  coverage is more reliably mature on 3.13; reproducibility beats novelty here, and
  Part 2 asks explicitly about pinning versions for reproducibility.
- **Written answers live in `results/*.md`, one file per assignment part.** The
  assignment asks for a PDF of theoretical answers; keeping them as Markdown in the
  repo means one source of truth that can be exported to PDF at the end.
- **Input data committed to the repo** (`hw_docs/`). The CSV is ~260 KB of public
  sample transcriptions, not real PHI, so committing it makes the submission
  runnable out of the box. Real PHI would never be committed — noted here because
  the assignment is set in a "no data leaves the hospital network" context.

### Artefacts
- `pyproject.toml`, `.python-version`, `steps_log.md`
- `results/part1_architecture_and_validation.md` (question scaffold, answers pending)

### Open questions
- None blocking. Part 1 answers are being written by the candidate; my role there is
  refinement and phrasing only.

### Addendum — working directly on `main`

Setup was initially done in a git worktree (`.claude/worktrees/samueli-assignment`).
Per instruction, worktrees are not used in this project: all work happens directly
in the main checkout on `main`.

- The worktree branch was fast-forwarded into `main` (it was a strict descendant,
  so no merge commit and no history rewrite), then the worktree and its branch were
  removed.
- `hw_docs/Oncology.csv` was untracked in the main checkout and committed on the
  branch, where git normalised its CRLF line endings to LF. Verified byte-identical
  modulo line endings (matching md5 after stripping `\r`) before letting git replace
  the working-tree copy, so no data was altered.
- `uv.lock` was salvaged from the worktree and committed. Deliberate: Q2.6 asks what
  must be pinned for a reported number to still be reproducible in six months, and
  the lockfile is part of that answer for this repo.

**Rationale for working on `main` directly:** the theoretical answers in `results/`
are written by the candidate, so the files must sit at the paths the IDE already
points at. A worktree risks two divergent copies of the same answer file.

---

## 2026-08-19 — Session 2: Part 1 answered

**Part:** Part 1 — Architecture & Validation (Q1.1 a–b, Q1.2 a–f).

### Done
- All eight Part 1 sub-questions answered. Answers were written by the candidate;
  my contribution was structural and phrasing refinement only, plus flagging
  claims that need external verification.
- `results/part1_architecture_and_validation.md` is complete (~1,700 words).
- Drafting hints (per-answer length guidance) stripped now that the part is
  complete — they were scaffolding for writing, not content for the submitted PDF.

### Decisions + rationale
- **Q1.1a — dropped the "Why include it" column.** It duplicated the closing
  paragraph and widened the table past readability. The tiering logic was promoted
  to a "Deployment thesis" lead-in above the table, and each row tagged with its
  tier (extraction / reasoning / reasoning alternative), so the reader has the
  two-tier frame before reaching the comparison.
- **Q1.1a — Hebrew caveat lifted out of all three weakness cells.** It appeared in
  every row, which spends three weakness cells on one point. Stated once after the
  table as a property of the open-weight landscape rather than a discriminator
  between models, with the mitigation deferred to Q1.1b where the question asks
  for it. This freed each cell for model-specific criticism.
- **Q1.1a — gpt-oss's MoE sizing moved into Strengths.** "117B total / ~5.1B active
  / single 80 GB GPU" is the reason a 120B reasoning model is deployable on-prem at
  all, so it belongs in Strengths rather than in a rationale column.
- **Q1.2a — reframed the human-evaluation "misses" cell.** "Expensive" is a cost
  constraint, not a blind spot; merged into "limited sample size, being cost-bound,
  so rare cases may be underrepresented" so the column answers the question asked.
- **Tab-separated pasted tables converted to real Markdown tables** and verified
  programmatically for consistent column counts (3 tables, all OK).

### Verification notes (open, candidate to confirm before submission)
- `Qwen3.5-27B` and `Nemotron 3 Super 120B-A12B`: exact model names, parameter
  counts, dense-vs-MoE architecture, context lengths and BF16 sizing were flagged
  as unverifiable against my knowledge cutoff (May 2026). The Qwen weakness cell
  asserts *dense* inference, which inverts if the model is in fact MoE.
  `gpt-oss-120b`'s figures were confirmed.
- arXiv 2512.11502 (Hebrew medical model, >5M de-identified records) — candidate
  confirmed the citation is correct.

### Suggested strengthenings (offered, not applied)
Recorded here so the reasoning is not lost if they are declined:
1. Q1.1a — licences are asymmetric (Apache 2.0 cited for gpt-oss only); licence is
   a genuine on-prem selection criterion.
2. Q1.1a — one clause on quantised serving (FP8/AWQ) and validating that
   quantisation does not degrade extraction quality.
3. Q1.2b — interpret model performance relative to inter-annotator agreement as the
   practical ceiling; note that Cohen's κ covers the categorical label while span
   agreement is usually pairwise F1 or Krippendorff's α.
4. Q1.2c — report metrics at an explicit operating threshold, not only
   threshold-free AUCs; note PR-AUC is prevalence-dependent and so not comparable
   across datasets with different prevalence.
5. Q1.2d — name κ for judge-vs-clinician agreement and compare it to the
   human-human ceiling.
6. Q1.2e — report the two faithfulness failure modes separately (span absent =
   fabricated evidence; span present but not entailing = unsupported inference),
   and normalise whitespace/casing before the span-presence check.
7. Q1.2f — a seventh cause from the human-factors family (output presented without
   evidence or confidence, so clinicians cannot verify it and lose trust even when
   the model is right); also test-set label noise.

### Artefacts
- `results/part1_architecture_and_validation.md` (complete)
- `.claude/settings.json` — `worktree.bgIsolation: none`, per instruction not to
  use worktrees in this project.

### Open questions
- Whether to apply any of the seven suggested strengthenings above.
- Part 2 not started; awaiting go-ahead.

---

## 2026-08-19 — Session 3: Part 1 strengthenings applied

**Part:** Part 1 — Architecture & Validation.

### Done
All seven strengthenings offered at the end of session 2 were approved and applied
(10 edits, since several touched more than one location):

1. **Q1.1a licences** — added per model in the name cell as inline code
   (`Apache 2.0`, `Apache 2.0`, `NVIDIA Open Model Licence`) rather than as a fifth
   column, which would have pushed the table past readable width. gpt-oss's licence
   was moved out of its Strengths cell so all three are stated in the same place.
2. **Q1.1a licence-as-criterion + quantisation** — one compact paragraph covering
   both: licence terms are load-bearing on-prem, and the BF16 GPU figures imply a
   quantised (FP8/AWQ) serving reality where "does quantisation degrade extraction
   quality or JSON adherence?" is a validation question, not an assumption.
3. **Q1.2b span-level agreement** — κ is correct for the fixed-category label but
   not for span extraction (no fixed category set, no well-defined negative class);
   added pairwise annotator F1, or Krippendorff's α where raters skip items or the
   rater count varies.
4. **Q1.2b human ceiling** — model metrics are now explicitly interpreted relative
   to inter-annotator agreement as the practical ceiling, with the residual gap to
   1.0 attributed to irreducible ambiguity rather than model defect.
5. **Q1.2c reporting discipline** — an explicit operating threshold chosen against
   the clinical FN:FP cost ratio (not a default 0.5) with point metrics reported at
   it, plus the note that PR-AUC's baseline is prevalence itself, so it is not
   comparable across sites or periods with different prevalence.
6. **Q1.2d judge trust made measurable** — judge-vs-clinician Cohen's κ compared
   against human-human κ on the same items, plus trusting the judge only over the
   distribution it was validated on.
7. **Q1.2e faithfulness failure modes split** — span-absent (fabricated evidence,
   a grounding failure fixed by constrained decoding / verbatim span copying) vs.
   span-present-but-not-entailing (unsupported inference, a reasoning failure fixed
   by prompt and model changes). Also: normalise whitespace, casing and punctuation
   before the presence check, or exact matching produces false failures on
   re-wrapped quotes. Metric now broken down by failure mode and by field.
8. **Q1.2f two further cause families** — human factors (output surfaced without
   evidence or confidence, so clinicians cannot verify it and withhold trust even
   when it is correct) and test-set label noise (F1 measures agreement with the
   gold standard, so wrong gold labels mean the metric confidently measures the
   wrong target). The cause table is now 8 rows against a required minimum of 4.

### Decisions + rationale
- **Comment convention added** at the top of the answers file as an HTML comment
  block: feedback is marked inline as `> **@claude:** …`, actioned, then the marker
  deleted, so `grep -n '@claude' results/*.md` returning nothing means everything
  has been handled. HTML comments do not render, so the convention stays out of the
  submitted PDF.
- **Length tradeoff accepted knowingly.** Part 1 grew from ~1,730 to ~2,455 words.
  The rubric prefers concise answers, so this is a deliberate call: the additions
  are substantive (named metrics, explicit ceilings, separated failure modes) rather
  than padding, and the density-per-sentence did not drop. Flagged for a trim pass
  before the PDF if it reads long as a whole.

### Artefacts
- `results/part1_architecture_and_validation.md` — Part 1 complete with all
  strengthenings; 3 tables verified for consistent column counts.

### Open questions
- `Qwen3.5-27B` and `Nemotron 3 Super 120B-A12B` specs still unverified against
  model cards — now also including the two licence strings just added.
- Candidate is doing a full re-read pass and will leave `@claude` comments.
- Part 2 not started; awaiting go-ahead.

### Comment round 1 — Q1.1a strengths/weaknesses as bullets

`@claude` comment: *"I want the strength and weaknesses as bullet points. Each in a
different line. Each bullet-point as concise as possible."* — kept as a table, with
the Strengths and Weaknesses cells bulleted.

**How the bullets are done, and why.** Markdown table cells cannot contain real
Markdown lists, so bullets inside a cell need either literal `•` characters joined by
`<br>`, or raw `<ul><li>` HTML. Chose `<br>•`: the bullet is plain text and `<br>` is
near-universally supported, so it survives GitHub rendering and Markdown→PDF export
alike. Raw `<ul>` inside a table cell renders correctly on GitHub but is commonly
dropped when Markdown is converted to LaTeX/PDF, which would silently lose the
bullets in the submitted artefact.

Bullets were compressed to short noun phrases per "as concise as possible" — no full
sentences. Counts: 4/2, 4/2, 5/3 strengths/weaknesses.

### Comment round 2 — Q1.1a licence example and precision in the table

Two `@claude` comments on Q1.1a, both handled.

**1. "you mention it in the Weaknesses of qwen3.5"** — correct catch: the caveat
paragraph claimed the Hebrew point was treated "once here", while Qwen's weaknesses
still carried "multilingual breadth is not evidence of Hebrew *clinical* competence".
Removed from Qwen's cell. Nemotron's "Hebrew is not an officially supported language"
was **kept**, because it is a different and genuinely model-specific claim — declared
language support is not the same thing as clinical competence. The caveat paragraph
was rewritten to draw exactly that distinction, so it no longer over-claims.
Qwen's vacated bullet was replaced with a role-based weakness ("not the accuracy
ceiling — hard negation and temporality cases must be escalated, not solved here"),
chosen because it needs no external spec verification, unlike a claim about the
model's feature set.

**2. "Give example to the license (LLAMA is one) the numeric precision should be part
of the table"** — both done:
- Llama named as the standard example of an open-weight-but-restricted licence
  (acceptable-use terms plus a monthly-active-user threshold requiring separate
  permission from Meta), contrasted against Apache 2.0.
- Precision moved into the table, grouped with tier and licence inside the model cell
  rather than as a fifth column — the table is already wide with bulleted cells, and
  tier/licence/precision are all deployment facts about the same model, so they cohere
  in one cell. VRAM figures labelled as weights-only approximations (≈2 bytes/param at
  BF16, ≈1 at FP8, KV cache excluded) so they are not read as measured numbers.
- Two knock-on tidies: Nemotron's GPU weakness tightened to "needs 2–4× the GPUs of
  gpt-oss at comparable precision" now that the table carries the figures, and the
  duplicated "fits a single 80 GB GPU" dropped from gpt-oss's strengths since the
  Precision line now states it.

**Candidate edit noted:** the "Selection is empirical, not a priori" paragraph was
deleted from Q1.1a in the same pass. Not restored — flagged to the candidate to confirm
whether that was deliberate, since it carried the answer's main judgment signal.

### Comment round 3 — Q1.1b condensed

`@claude` comment: *"the above q1.1.b answer is very good. can you make the above more
concise?"*

Condensed 211 → 159 words (−25%) with no substantive loss. Every point survives: the
English-dominant training imbalance, morphology/tokenization, code-switching with
transliterated terms and shorthand, the non-transfer conclusion, the two supporting
literature claims, and the full three-step mitigation with its citation. What went was
connective padding ("I would first…", "I would measure both… rather than relying on…")
and hedging; sentences were merged and the two halves given bold **Concern.** /
**Mitigation.** leads so the structure is visible at a glance. Also re-wrapped to the
file's ~95-character convention, since the pasted original was unwrapped.

Restored the blank line before the `### b)` heading, which an edit had removed —
Markdown headings need a preceding blank line to render reliably across parsers.

**Candidate edits noted, not reverted:** the *Serving precision* half of the
deployment-constraints paragraph was deleted, and the remaining half demoted from a bold
lead to *Licence constraints:*. Consequence flagged to the candidate: the table's VRAM
figures now carry no "weights-only approximation, KV cache excluded" caveat, so they read
as measured numbers, and strengthening #2 (validating that quantisation does not degrade
extraction quality or JSON adherence) is no longer stated anywhere.

### Comment round 4 — Q1.2a mitigation column

Four comments, all on Q1.2a. Note one was written `@this` rather than `@claude`, so the
`grep '@claude'` convention missed it — worth keeping to the one marker.

**1. "add mitigation column which will mitigate the 'misses' column"** — table is now
five columns: Framework / Method / Catches / Misses / Mitigation. Each mitigation
answers that row's specific miss rather than being generic advice.

**2. "is it for both binary labels and extracted fields?"** — yes, both. Made explicit
in the Method cell: "Compare model outputs — **both the binary label and the extracted
fields** — against an independently clinician-annotated, adjudicated test set." The
question was fair: the original wording left it ambiguous, and the assignment states the
pipeline emits both.

**3. "extracted text may vary thus makes it hard to compare to human labels. Requires a
solution"** — a genuine miss that was absent, now added as a second bullet in that cell:
free-text extractions vary in wording and span boundaries, so they do not compare to a
human annotation by exact match. The paired mitigation is to score spans by normalised
and partial-overlap matching (character-offset IoU) rather than string equality, and to
reserve exact match for closed-vocabulary fields.

**4. "@this approach mitigates the problem I mentioned in the miss of Human-goldstandard
evaluation"** — correct, and now stated in both directions: the automated framework's
Catches cell names the span-variance problem explicitly, and the human row's mitigation
points forward to it. The closing paragraph was extended to generalise the observation —
the mitigations are largely *each other*, since the span-variance limit of human
comparison is answered by automated partial-overlap scoring while the correctness blind
spot of automated scoring is answered by anchoring back to the gold standard.

**Consistency tidy:** the candidate had removed the `**Answer:**` markers from Q1.1a,
Q1.1b, Q1.2a and Q1.2b; removed the four remaining ones (Q1.2c–f) so the document does
not mix both styles.
