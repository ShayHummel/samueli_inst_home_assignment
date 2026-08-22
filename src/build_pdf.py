"""Build the submission PDF required by the assignment's Logistics section.

    Submit: (1) a PDF file with the theoretical answers and prompt design;
            (2) GitHub repo with your Python (.py) and SQL.

This assembles (1) from the same sources as (2), so the two cannot disagree:

* the four ``results/*.md`` answer documents, in order;
* an appendix of prompt text read **live** from :mod:`src.prompts`, rather than
  copy-pasted. A prompt edited in the code appears edited in the PDF on the next
  build, which is the whole reason this is a script and not a hand-made document.

``uv run samueli-pdf`` writes ``results/Samueli_Home_Assignment_Shay_Hummel.pdf``.

External tools, all checked up front with an actionable message rather than a
traceback: ``pandoc`` (Markdown to HTML), Google Chrome (HTML to PDF, headless),
and ``npx`` (Mermaid diagram to SVG; the diagram degrades to its source text if
absent, so this one is optional).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if not __package__:  # pragma: no cover - only reachable when run by file path
    raise SystemExit(
        "Run this as a module, not a file path:\n"
        "    uv run python -m src.build_pdf\n"
        "or use the installed entry point:\n"
        "    uv run samueli-pdf"
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
OUTPUT_PDF = RESULTS_DIR / "Samueli_Home_Assignment_Shay_Hummel.pdf"

#: Answer documents in submission order.
ANSWER_DOCS = (
    "part1_architecture_and_validation.md",
    "part2_prompt_design.md",
    "part3_sql_and_pipeline.md",
    "part4_embeddings_and_search.md",
)

#: The four pipeline stages, as (heading, module attribute) pairs. Read from
#: ``src.prompts`` at build time — see the module docstring.
PROMPT_STAGES = (
    ("Stage 1 — Reasoning", "stage1_reasoning"),
    ("Stage 2 — Structuring", "stage2_structuring"),
    ("Stage 4 — Repair", "repair"),
    ("Stage 5 — Adversarial self-check", "self_check"),
)

CHROME = Path(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)

# Print stylesheet. Deliberately plain: this is a document to be read by a
# reviewer, not a brochure.
CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: "Charter", "Georgia", serif; font-size: 10.5pt; line-height: 1.45;
  color: #111; max-width: none; margin: 0;
}
h1 { font-size: 19pt; margin: 0 0 0.4em; page-break-before: always; }
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 14pt; margin: 1.5em 0 0.4em; border-bottom: 1px solid #bbb;
     padding-bottom: 0.15em; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 1.2em 0 0.3em; page-break-after: avoid; }
h4 { font-size: 10.5pt; margin: 1em 0 0.3em; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
code, pre { font-family: "SF Mono", "Menlo", monospace; font-size: 8.6pt; }
pre {
  background: #f6f6f4; border: 1px solid #ddd; border-radius: 3px;
  padding: 7px 9px; white-space: pre-wrap; word-wrap: break-word;
  page-break-inside: avoid;
}
code { background: #f2f2f0; padding: 0.5px 3px; border-radius: 2px; }
pre code { background: none; padding: 0; }
table {
  border-collapse: collapse; width: 100%; margin: 0.8em 0;
  font-size: 9pt; page-break-inside: avoid;
}
th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left;
         vertical-align: top; }
th { background: #eeeeec; }
blockquote {
  margin: 0.7em 0; padding: 0.2em 0 0.2em 0.9em;
  border-left: 3px solid #ccc; color: #333;
}
img, svg { max-width: 100%; height: auto; page-break-inside: avoid; }
hr { border: none; border-top: 1px solid #ddd; margin: 1.4em 0; }
a { color: #14418b; text-decoration: none; }
/* pandoc --standalone renders the `title` metadata as a visible block at the top
   of the body. The metadata is wanted (Chrome copies it into the PDF's title
   field) but the visible copy would sit above and duplicate the title page. */
header#title-block-header, h1.title, p.title { display: none; }
.titlepage { page-break-after: always; padding-top: 32mm; text-align: center; }
.titlepage .t { font-size: 25pt; font-weight: 600; line-height: 1.2; }
.titlepage .s { font-size: 13pt; color: #444; margin-top: 0.7em; }
.titlepage .m { font-size: 10.5pt; color: #555; margin-top: 3.2em; line-height: 1.9; }
.titlepage .n { font-size: 9pt; color: #666; margin-top: 3.2em;
                text-align: left; border-top: 1px solid #ddd; padding-top: 1em; }
"""

HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
MERMAID_BLOCK = re.compile(r"^```mermaid\n(.*?)^```", re.DOTALL | re.MULTILINE)


def _require(tool: str, hint: str) -> None:
    if shutil.which(tool) is None:
        raise SystemExit(f"error: `{tool}` not found on PATH.\n  {hint}")


def check_tools() -> bool:
    """Verify external tools. Returns True if Mermaid rendering is available."""
    _require("pandoc", "Install with: brew install pandoc")
    if not CHROME.exists():
        raise SystemExit(
            f"error: Google Chrome not found at {CHROME}.\n"
            "  It is used headless to turn HTML into PDF. Install Chrome, or "
            "adjust CHROME in this module."
        )
    if shutil.which("npx") is None:
        print("  note: npx not found - the ER diagram will appear as source text.")
        return False
    return True


def render_mermaid(source: str, out_svg: Path) -> bool:
    """Render one Mermaid diagram to SVG. Returns False if the render failed."""
    mmd = out_svg.with_suffix(".mmd")
    mmd.write_text(source, encoding="utf-8")
    try:
        subprocess.run(
            [
                "npx", "--yes", "@mermaid-js/mermaid-cli@latest",
                "-i", str(mmd), "-o", str(out_svg), "-b", "white",
            ],
            check=True, capture_output=True, timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"  note: Mermaid render failed ({type(exc).__name__}); "
              "keeping diagram source.")
        return False
    return out_svg.exists()


def prepare_markdown(text: str, workdir: Path, mermaid_ok: bool) -> str:
    """Strip working-process comments and swap Mermaid blocks for rendered SVG."""
    # The COMMENTS TO CLAUDE blocks are a working convention between me and the
    # repo, not submission content. They are HTML comments so they never render,
    # but stripping them keeps them out of the intermediate HTML as well.
    text = HTML_COMMENT.sub("", text)

    counter = [0]

    def swap(match: re.Match[str]) -> str:
        if not mermaid_ok:
            return match.group(0)
        counter[0] += 1
        svg = workdir / f"diagram_{counter[0]}.svg"
        if not render_mermaid(match.group(1), svg):
            return match.group(0)
        return f"![Entity-relationship diagram]({svg.as_posix()})"

    return MERMAID_BLOCK.sub(swap, text)


def prompt_appendix() -> str:
    """Render the prompt templates from source, so the PDF cannot drift."""
    from . import prompts

    out = [
        "\n\n# Appendix — Prompt design\n",
        (
            "The prompts referenced throughout Part 2. This appendix is generated "
            "directly from the modules under [`src/prompts/`](../src/prompts/) at "
            "build time, so it is the text the pipeline actually sends, not a "
            "transcription of it.\n"
        ),
        (
            "Braces in a LangChain `f-string` template are doubled to escape them "
            "(`{{` renders as a literal `{`); the placeholders below in single "
            "braces are the real substitution points.\n"
        ),
    ]
    for heading, module_name in PROMPT_STAGES:
        module = getattr(prompts, module_name)
        variables = ", ".join(f"`{v}`" for v in module.INPUT_VARIABLES)
        out.append(f"\n## {heading}\n")
        out.append(f"Module: `src/prompts/{module_name}.py`\n")
        out.append(f"Input variables: {variables or '_none_'}\n")
        out.append("\n### System prompt\n")
        out.append(f"```text\n{module.SYSTEM_TEMPLATE.strip()}\n```\n")
        out.append("\n### User prompt\n")
        out.append(f"```text\n{module.USER_TEMPLATE.strip()}\n```\n")
    return "\n".join(out)


def title_page() -> str:
    return """<div class="titlepage">
<div class="t">Technical Home Assignment</div>
<div class="s">NLP Research Scientist &mdash; Clinical Text &amp; LLMs</div>
<div class="m">
Samueli Institute &middot; Data Research Department<br>
Shay Hummel
</div>
<div class="n">
<strong>Theoretical answers and prompt design.</strong> Parts 1&ndash;4 in full, followed by
an appendix containing the prompt templates, generated from the source modules at build time.
<br><br>
<strong>Code.</strong> The accompanying repository holds the Python and SQL:
<code>src/</code> for the pipeline and evaluation harness, <code>sql/</code> for the Task 3.1
queries, <code>tests/</code> for the test suite. See <code>README.md</code> to run it.
<br><br>
<strong>AI assistance.</strong> Written with Claude Code, as permitted by the Logistics
section. <code>steps_log.md</code> in the repository records what was decided at each step
and why, including the defects found by running the code rather than reading it.
</div>
</div>
"""


def build() -> Path:
    mermaid_ok = check_tools()
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        chunks = [title_page()]
        for name in ANSWER_DOCS:
            path = RESULTS_DIR / name
            if not path.exists():
                raise SystemExit(f"error: missing answer document {path}")
            print(f"  + {name}")
            chunks.append(prepare_markdown(
                path.read_text(encoding="utf-8"), workdir, mermaid_ok
            ))
        print("  + prompt appendix (from src/prompts/)")
        chunks.append(prompt_appendix())

        combined = workdir / "submission.md"
        combined.write_text("\n\n".join(chunks), encoding="utf-8")

        css = workdir / "print.css"
        css.write_text(CSS, encoding="utf-8")
        html = workdir / "submission.html"

        print("  > pandoc")
        subprocess.run(
            [
                "pandoc", str(combined),
                "--from", "gfm+raw_html",
                "--to", "html5",
                "--standalone",
                "--embed-resources",
                "--css", str(css),
                "--metadata", "title=Samueli Institute Home Assignment - Shay Hummel",
                "-o", str(html),
            ],
            check=True, cwd=REPO_ROOT,
        )

        print("  > chrome --headless --print-to-pdf")
        OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                str(CHROME), "--headless", "--disable-gpu", "--no-sandbox",
                "--no-pdf-header-footer",
                f"--print-to-pdf={OUTPUT_PDF}",
                html.as_uri(),
            ],
            check=True, capture_output=True, timeout=180,
        )

    if not OUTPUT_PDF.exists():
        raise SystemExit("error: Chrome reported success but wrote no PDF.")
    return OUTPUT_PDF


def main() -> int:
    print("Building submission PDF")
    pdf = build()
    size_kb = pdf.stat().st_size / 1024
    print(f"\n  wrote {pdf.relative_to(REPO_ROOT)}  ({size_kb:,.0f} KB)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
