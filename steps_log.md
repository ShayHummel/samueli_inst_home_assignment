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
