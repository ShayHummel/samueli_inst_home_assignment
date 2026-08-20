"""Exploratory data analysis of `hw_docs/Oncology.csv`.

Run with:

    uv run python -m src.eda

The questions this answers are the ones that change how Task 3.2 is built, not a
generic column survey:

* How long are the transcriptions? Decides whether they fit a context window and
  whether chunking is needed.
* How many notes actually contain an assessable statement about disease status or
  treatment response? This sets the expected abstention rate from the D13 rule, and
  it is the single most consequential number in the dataset.
* Which of the Part-2 traps occur naturally in this corpus? A trap that appears
  here is a real risk, not a hypothetical one.
* Is the corpus duplicated or structurally uniform in ways that would inflate an
  evaluation?
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).resolve().parent.parent / "hw_docs" / "Oncology.csv"

# Response-status vocabulary. Word boundaries matter: a bare "PD" search hits
# "PDA" and "COPD", and an unanchored "CR" hits "SACRAL" and "microscopic".
PD_PATTERNS = {
    "progressive disease": r"\bprogressive disease\b",
    "progression": r"\bprogress(?:ion|ed|ing|es)\b",
    "PD (abbrev)": r"(?<![A-Za-z])PD(?![A-Za-z])",
    "new/enlarging lesion": r"\bnew\b[^.]{0,40}\b(?:lesion|metasta|mass|nodule)",
    "metastatic": r"\bmetastat|\bmetastas",
}

NON_PD_PATTERNS = {
    "complete response / CR": r"\bcomplete response\b|(?<![A-Za-z])CR(?![A-Za-z])",
    "partial response / PR": r"\bpartial response\b|(?<![A-Za-z])PR(?![A-Za-z])",
    "stable disease / SD": r"\bstable disease\b|(?<![A-Za-z])SD(?![A-Za-z])",
    "remission": r"\bremission\b",
    "no evidence of disease": r"\bno evidence of\b",
}

# The Part-2 traps, as regexes. Each one that fires here is a real risk in this corpus.
TRAP_PATTERNS = {
    "negated progression": r"\bno\b[^.]{0,30}\b(?:evidence of\s+)?progress",
    "hypothetical / conditional": r"\bif\b[^.]{0,40}\bprogress|\bshould\b[^.]{0,30}\bprogress",
    "hedged": r"\b(?:rule out|cannot exclude|concern for|suspicious for|possible)\b",
    "family history subject": r"\b(?:mother|father|sister|brother|family history|aunt|uncle)\b",
    "historical timepoint": r"\b(?:previously|in 20\d\d|history of|status post|s/p)\b",
}

DEID_PATTERNS = {
    "redacted name (Dr. X / Dr. Y)": r"\bDr\.\s+[A-Z]\b",
    "placeholder token (ABC / ABCD / XYZ)": r"\b(?:ABCD?|XYZ)\b",
    "blanked span (____)": r"_{3,}",
}


@dataclass
class Finding:
    label: str
    count: int
    total: int

    @property
    def pct(self) -> float:
        return 100.0 * self.count / self.total if self.total else 0.0

    def __str__(self) -> str:
        return f"{self.label:<40} {self.count:>4}  ({self.pct:5.1f}%)"


def load(path: Path = DATA_PATH) -> pd.DataFrame:
    """Load the corpus, normalising the unnamed index column."""
    df = pd.read_csv(path)
    df = df.rename(columns={"Unnamed: 0": "source_row_id"})
    # Every text column in this export is padded with leading/trailing spaces.
    for col in ("description", "medical_specialty", "sample_name", "transcription"):
        df[col] = df[col].astype(str).str.strip()
    return df


def count_matching(series: pd.Series, patterns: dict[str, str]) -> list[Finding]:
    total = len(series)
    return [
        Finding(label, int(series.str.contains(rx, case=False, regex=True).sum()), total)
        for label, rx in patterns.items()
    ]


def assessable_mask(df: pd.DataFrame) -> pd.Series:
    """Notes containing at least one response-status or progression statement.

    Deliberately generous: it counts a note as assessable if *any* status token
    appears anywhere. So it is an upper bound on how many notes a PD/Non-PD
    classifier can meaningfully label, and the true figure is lower.
    """
    every = {**PD_PATTERNS, **NON_PD_PATTERNS}
    combined = "|".join(f"(?:{rx})" for rx in every.values())
    return df["transcription"].str.contains(combined, case=False, regex=True)


def report(df: pd.DataFrame) -> str:
    out: list[str] = []
    add = out.append
    n = len(df)

    add("=" * 68)
    add("EDA — hw_docs/Oncology.csv")
    add("=" * 68)

    add("\n-- Shape and integrity " + "-" * 44)
    add(f"rows: {n}   columns: {df.shape[1]}")
    add(f"columns: {', '.join(df.columns)}")
    add(f"nulls: {df.isna().sum().sum()}")
    add(f"exact duplicate transcriptions: {int(df['transcription'].duplicated().sum())}")
    add(f"distinct medical_specialty values: {df['medical_specialty'].nunique()} "
        f"-> {df['medical_specialty'].unique().tolist()}")
    add(f"distinct sample_name values: {df['sample_name'].nunique()}")

    add("\n-- Transcription length " + "-" * 44)
    chars = df["transcription"].str.len()
    words = df["transcription"].str.split().str.len()
    add(f"characters: min {chars.min()}  median {int(chars.median())}  "
        f"mean {int(chars.mean())}  max {chars.max()}")
    add(f"words:      min {words.min()}  median {int(words.median())}  "
        f"mean {int(words.mean())}  max {words.max()}")
    add(f"approx tokens (words x 1.3): median {int(words.median() * 1.3)}  "
        f"max {int(words.max() * 1.3)}")
    add(f"notes over 2000 words: {int((words > 2000).sum())}")

    add("\n-- Assessability (the number that matters) " + "-" * 25)
    mask = assessable_mask(df)
    add(str(Finding("notes with ANY status/progression token", int(mask.sum()), n)))
    add(str(Finding("notes with NO such token -> must abstain", int((~mask).sum()), n)))

    add("\n-- PD-side vocabulary " + "-" * 46)
    for f in count_matching(df["transcription"], PD_PATTERNS):
        add(str(f))

    add("\n-- Non-PD-side vocabulary " + "-" * 42)
    for f in count_matching(df["transcription"], NON_PD_PATTERNS):
        add(str(f))

    add("\n-- Part-2 traps occurring naturally " + "-" * 32)
    for f in count_matching(df["transcription"], TRAP_PATTERNS):
        add(str(f))

    add("\n-- De-identification artefacts " + "-" * 37)
    for f in count_matching(df["transcription"], DEID_PATTERNS):
        add(str(f))

    add("\n-- Ambiguity: notes carrying BOTH PD and Non-PD vocabulary " + "-" * 9)
    pd_any = df["transcription"].str.contains(
        "|".join(f"(?:{r})" for r in PD_PATTERNS.values()), case=False, regex=True
    )
    non_pd_any = df["transcription"].str.contains(
        "|".join(f"(?:{r})" for r in NON_PD_PATTERNS.values()), case=False, regex=True
    )
    add(str(Finding("both PD and Non-PD tokens present", int((pd_any & non_pd_any).sum()), n)))
    add(str(Finding("PD tokens only", int((pd_any & ~non_pd_any).sum()), n)))
    add(str(Finding("Non-PD tokens only", int((~pd_any & non_pd_any).sum()), n)))
    add(str(Finding("neither", int((~pd_any & ~non_pd_any).sum()), n)))

    add("\n-- Section structure " + "-" * 47)
    header_re = re.compile(r"([A-Z][A-Z /&'\-]{3,}):")
    headers = pd.Series(
        [h.strip() for text in df["transcription"] for h in header_re.findall(text)]
    )
    add(f"distinct ALL-CAPS section headers: {headers.nunique()}")
    add("most common:")
    for name, count in headers.value_counts().head(8).items():
        add(f"  {name:<38} {count:>4}")

    add("\n" + "=" * 68)
    return "\n".join(out)


def main() -> int:
    """Entry point for `samueli-eda`."""
    print(report(load()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
