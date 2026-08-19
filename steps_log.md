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
