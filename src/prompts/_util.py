"""Helpers shared by the prompt modules."""

from __future__ import annotations


def escape_braces(text: str) -> str:
    """Escape literal braces so an f-string prompt template leaves them alone.

    LangChain's default ``template_format="f-string"`` treats ``{name}`` as a
    variable. Our prompts embed a literal JSON schema, so every brace in that
    block has to be doubled or LangChain reads ``{"classification": ...}`` as a
    variable named ``"classification": ...`` and raises at render time.

    Escaping here rather than by hand keeps the prompt source readable and
    removes a whole class of silent template bugs.
    """
    return text.replace("{", "{{").replace("}", "}}")


#: The JSON contract, written for a model to read rather than as formal JSON Schema.
#: A test asserts the field names here match ``src.schema.ClinicalClassification``,
#: so this cannot drift from the Pydantic model without the suite failing.
JSON_CONTRACT = """{
  "classification":      "PD" or "Non-PD",
  "confidence_score":    an integer from 0 to 100,
  "supporting_evidence": an array of strings, each an exact quote from the summary,
  "clinical_reasoning":  a string
}"""

#: Brace-escaped form, safe to embed in an f-string template.
JSON_CONTRACT_ESCAPED = escape_braces(JSON_CONTRACT)


def as_json_string(text: str) -> str:
    """JSON-encode ``text`` for embedding as a value in a JSON-delimited prompt.

    The note is delivered to the model inside a JSON object rather than XML-style
    tags. JSON encoding is what makes that boundary actually hold: quotes and
    newlines in the note are escaped, so a note cannot terminate its own container
    and continue as instructions — an XML tag can be closed by text that merely
    contains ``</clinical_summary>``.

    The cost is that the model sees escaped text (``\\n``, ``\\"``), which risks it
    quoting the *escaped* form as evidence and failing the verbatim grounding check.
    Two mitigations: the stage-1 prompt states explicitly that quotes must reproduce
    the clinical text and not its JSON escaping, and
    ``validation.normalise_for_matching`` collapses literal escape sequences so an
    escaped quote still matches its source.
    """
    import json

    return json.dumps(text, ensure_ascii=False)
