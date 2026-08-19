"""Output contract for the PD / Non-PD classification pipeline (assignment 2.3).

The schema is fixed by the assignment:

    {
      "classification":      "PD" | "Non-PD",
      "confidence_score":    0.0-1.0,
      "supporting_evidence": ["<exact quote from the text>", "..."],
      "clinical_reasoning":  "<brief explanation of the decision>"
    }

Two rules are enforced here rather than left to the prompt, because a prompt can
only ask and a validator can refuse:

* ``extra="forbid"`` — an output carrying fields we never asked for is a
  malformed output, not a helpful one. Silently dropping them would hide that
  the model went off-contract.
* A ``PD`` verdict with no supporting evidence is rejected. Asserting that a
  patient's cancer is progressing while quoting nothing from the note is exactly
  the fabrication that Q1.2e's faithfulness check exists to catch, so it must
  never validate.

The mirror case — ``Non-PD`` with no evidence — is *legitimate* and carries
meaning: it is the abstention signature agreed for D13 (nothing assessable in
the note). See :attr:`ClinicalClassification.is_abstention`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Confidence at or below this value, combined with no supporting evidence, marks
#: a record as "nothing assessable in the note" rather than "assessed as Non-PD".
#: Fixed by the D13 decision and by the stage-1 prompt, which instructs 0.2 or below.
ABSTENTION_CONFIDENCE_CEILING = 0.2


class Classification(str, Enum):
    """The two permitted labels. Values are the exact strings the schema requires."""

    PD = "PD"
    NON_PD = "Non-PD"


class ClinicalClassification(BaseModel):
    """A validated pipeline output for a single clinical summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    classification: Classification
    confidence_score: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    clinical_reasoning: str = Field(min_length=1)

    @model_validator(mode="after")
    def _pd_requires_evidence(self) -> ClinicalClassification:
        if self.classification is Classification.PD and not self.supporting_evidence:
            raise ValueError(
                "classification 'PD' requires at least one supporting_evidence quote; "
                "asserting progression with no quote from the note is unsupported by "
                "construction"
            )
        return self

    @model_validator(mode="after")
    def _evidence_quotes_are_non_empty(self) -> ClinicalClassification:
        for i, quote in enumerate(self.supporting_evidence):
            if not quote.strip():
                raise ValueError(f"supporting_evidence[{i}] is empty or whitespace only")
        return self

    @property
    def is_abstention(self) -> bool:
        """True when this record means "no assessable content", not "assessed Non-PD".

        The D13 signature: a ``Non-PD`` label with no evidence and a confidence at
        or below the ceiling. Machine-detectable by design, so the pipeline can
        route these to a clinician instead of reporting them as negative findings.
        """
        return (
            self.classification is Classification.NON_PD
            and not self.supporting_evidence
            and self.confidence_score <= ABSTENTION_CONFIDENCE_CEILING
        )


#: Field names the prompts describe to the model. Kept here so a test can assert
#: the prose schema block in ``src/prompts`` has not drifted from this model.
SCHEMA_FIELD_NAMES: tuple[str, ...] = tuple(ClinicalClassification.model_fields)
