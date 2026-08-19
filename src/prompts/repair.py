"""Stage 4 — schema repair (assignment 2.4).

Invoked only when stage 3 rejects stage 2's output. The model is shown its own
invalid output together with the concrete validator error, and asked to return a
corrected object.

Two constraints make this a repair rather than a second opinion:

* It receives the **validator's error text**, not a vague "that was wrong". A
  model that is told ``confidence_score: input should be less than or equal to 1``
  can fix that; a model told "invalid JSON" guesses.
* It is forbidden from changing clinical content. Repair exists to fix
  *structure*. If a repair call were free to revise the verdict, a formatting
  failure could silently become a clinical disagreement, and the verdict-drift
  check in stage 3 would start firing on genuine reasoning changes.

Retries are bounded by the caller and every failure is counted by type — a
repair loop that retries forever, or that swallows the reason, is the ``except:
pass`` the assignment explicitly fails.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from ._util import JSON_CONTRACT_ESCAPED

SYSTEM_TEMPLATE = f"""You are a JSON repair function. A previous attempt produced output \
that failed schema validation. You are given that output and the exact validation error. \
Return a corrected JSON object.

Rules:
- Output EXACTLY one JSON object and nothing else. No prose, no explanation, no markdown
  code fences, no leading or trailing text.
- Fix ONLY the structural problem described in the error. Do not change the clinical
  meaning: keep the same classification, the same evidence quotes character-for-character,
  and the same reasoning. You are correcting format, not revising a judgement.
- If a required field is missing and its value cannot be recovered from the invalid output,
  use the most conservative valid value: "Non-PD" for classification, 0.0 for
  confidence_score, an empty array for supporting_evidence, and for clinical_reasoning a
  string stating that the value could not be recovered.
- Never invent an evidence quote. If no quote is recoverable, return an empty array.

Required schema:
{JSON_CONTRACT_ESCAPED}"""

USER_TEMPLATE = """The output that failed validation:

<invalid_output>
{invalid_output}
</invalid_output>

The validation error:

<validation_error>
{validation_error}
</validation_error>

Return the corrected JSON object."""

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM_TEMPLATE), ("human", USER_TEMPLATE)]
)

#: Variables the caller must supply.
INPUT_VARIABLES = ("invalid_output", "validation_error")
