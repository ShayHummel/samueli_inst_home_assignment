# Samueli Institute — Home Assignment, NLP Research Scientist

Clinical text & LLMs: an on-prem PD / Non-PD classification pipeline, its validation
strategy, the supporting SQL, and an evaluation harness.

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.13 (uv will fetch the interpreter
if needed).

```bash
uv sync                                  # one command; installs everything incl. pytest
uv run pytest -q                         # 106 tests
uv run ruff check .                      # lint: unused imports, undeclared packages

uv run samueli-eda                       # EDA over hw_docs/Oncology.csv
uv run samueli-evaluate                  # Task 3.2 evaluation
uv run samueli-pipeline                  # walkthrough: 14 scenarios, one set per stage
```

The three commands above are console entry points and work from any directory. The equivalent
module form also works: `uv run python -m src.eda`, and so on.

> **Do not run these by file path.** `python src/pipeline.py` fails with
> `ImportError: attempted relative import with no known parent package`, because a file run by
> path has no parent package for `from .prompts import …` to resolve against. The modules detect
> this and print the correct command instead of a stack trace. **In PyCharm**, set the run
> configuration's target to **module name** (`src.pipeline`) rather than **script path** — the
> default is script path, which is exactly the failing case.

`uv sync` alone is enough — there are no optional extras to remember. Every third-party package
imported anywhere in `src/` or `tests/` is declared in `pyproject.toml`, and `ruff check`
enforces that nothing undeclared or unused creeps back in.

## Where the answers are

| Document | Covers |
| --- | --- |
| [`results/part1_architecture_and_validation.md`](results/part1_architecture_and_validation.md) | Part 1 — model selection (Q1.1), validation strategy (Q1.2 a–f) |
| [`results/part2_prompt_design.md`](results/part2_prompt_design.md) | Part 2 — clarifying questions, prompt design, schema, adherence, edge cases, reproducibility, injection (2.1–2.7) |
| [`results/part3_sql_and_pipeline.md`](results/part3_sql_and_pipeline.md) | Part 3 — ER diagram, SQL (3.1), evaluation pipeline (3.2), written questions (3.3) |
| [`results/part4_embeddings_and_search.md`](results/part4_embeddings_and_search.md) | Part 4 — embedding model selection, vector store, RAG failure modes (E.1–E.3) |
| [`results/eda_report.md`](results/eda_report.md) | One-page EDA of `Oncology.csv` |
| [`steps_log.md`](steps_log.md) | Working log: what was done, what was decided, and why |

## Code layout

```
src/
  schema.py        Pydantic output contract (2.3)
  prompts/         LangChain templates, one module per pipeline stage (2.2)
    stage1_reasoning.py    reason over the note -> prose + VERDICT line
    stage2_structuring.py  format that analysis -> strict JSON
    repair.py              bounded schema repair on validation failure
    self_check.py          adversarial chain-of-thought audit
  validation.py    verify_output(): extraction, schema, verdict drift, quote grounding
  pipeline.py      classify_note(): the flow that drives all four prompts
  eda.py           exploratory analysis of Oncology.csv
  evaluate.py      Task 3.2: labels, mocked LLM, robust parsing, metrics

sql/
  schema.sql       DDL for the Task 3.1 clinical schema
  queries/         one file per query, each with its assumptions in a header

tests/             106 tests
hw_docs/           the assignment PDF and Oncology.csv
```

## The pipeline in one picture

```
note ──> stage 1 (reason)  ──> stage 2 (structure) ──> stage 3 (validate) ──> result
             reasoning tier        extraction tier         Python, not an LLM
             prose + VERDICT       strict JSON             Pydantic + verdict
             no JSON               never sees the note     drift + quote grounding
                                          │                        │ fail
                                          └─ stage 4 (repair) <────┘
                                             bounded retries, error text supplied

                          stage 5 (audit, optional): adversarial re-read of the
                          note against the output. Different model family.
```

`classify_note()` takes the LLM as a plain callable, so it runs against vLLM, Ollama, an HTTP
endpoint, or a test double without changes:

```python
from src.pipeline import classify_note

result = classify_note(note_text, reasoning_llm=big_llm, structuring_llm=small_llm)
if result:
    print(result.classification.classification.value)   # "PD" | "Non-PD"
else:
    print(result.failure_type, result.failure_detail)   # typed, never swallowed
```

## Running the SQL tests

The queries use PostgreSQL-specific constructs (`ILIKE`, `DISTINCT ON`,
`LEFT JOIN LATERAL`), so they are tested against a real server rather than SQLite.
`tests/conftest.py` starts a **throwaway cluster** with `initdb` in a temp directory on a Unix
socket — no Docker, no port collisions, no pre-existing server:

```bash
uv run pytest tests/test_sql_queries.py -v
```

If PostgreSQL is not installed the SQL tests **skip with a clear reason** and the rest of the
suite still passes. To enable them:

```bash
brew install postgresql@18      # macOS
```

To run a query by hand against your own database:

```bash
psql "$DATABASE_URL" -f sql/schema.sql
psql "$DATABASE_URL" -f sql/queries/01_neurology_patients_2025.sql
```

## Reproducibility

Part 2.6 argues that a reported number must still be reproducible in six months, so the code
holds to it:

- `uv.lock` is committed; `uv sync` reproduces the exact dependency set.
- Python is pinned to 3.13 in `.python-version`.
- Every random draw is seeded (`DEFAULT_SEED = 20260819`, overridable with `--seed`).
- The mock's per-note seed uses SHA-256, **not** the builtin `hash()`, which Python salts per
  process — that bug made an earlier version of this pipeline silently irreproducible.

Two consecutive `uv run python -m src.evaluate` invocations produce byte-identical output.

## A note on the Task 3.2 numbers

The ground-truth labels are random **by instruction**, so the reported metrics measure the
evaluation harness, not clinical accuracy. The program prints this caveat itself. With 90
records at ~5% prevalence, F1's 95% confidence interval spans `[0.000, 1.000]` — which is the
point: it demonstrates the "small test set" failure mode from Q1.2f on our own evaluation.

## AI assistance

Written with Claude Code, per the assignment's Logistics section. `steps_log.md` records what
was decided at each step and why, including two bugs the assistant found by running the
pipeline rather than reading it.
