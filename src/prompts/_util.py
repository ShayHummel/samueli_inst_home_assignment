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
  "confidence_score":    a number from 0.0 to 1.0,
  "supporting_evidence": an array of strings, each an exact quote from the summary,
  "clinical_reasoning":  a string
}"""

#: Brace-escaped form, safe to embed in an f-string template.
JSON_CONTRACT_ESCAPED = escape_braces(JSON_CONTRACT)
