"""Output contracts for the PD / Non-PD classification pipeline (assignment 2.3).

**Two contracts, one boundary.** The assignment fixes the pipeline's output schema,
including ``confidence_score: 0.0-1.0``, and that is what leaves the pipeline. But
the intermediate stages speak a 0–100 integer scale, because LLMs emit coarse
percentages far more consistently than fine-grained floats — asked for a decimal,
they cluster on a handful of round values (0.9, 0.95) and imply a resolution they
do not have.

So:

* :class:`RawClassification` — what stage 2 emits. Confidence on **0–100**.
* :class:`ClinicalClassification` — what the pipeline returns. Confidence on
  **0.0–1.0**, exactly as the assignment specifies.

:meth:`RawClassification.to_output` is the only crossing point, so the scale change
happens in one place and cannot leak. Nothing downstream ever sees a 0–100 value.

Two rules are enforced in the models rather than left to the prompt, because a
prompt can only ask and a validator can refuse:

* ``extra="forbid"`` — an output carrying fields we never asked for is malformed,
  not helpful. Silently dropping them would hide that the model went off-contract.
* A ``PD`` verdict with no supporting evidence is rejected. Asserting that a
  patient's cancer is progressing while quoting nothing from the note is exactly
  the fabrication that Q1.2e's faithfulness check exists to catch.

The mirror case — ``Non-PD`` with no evidence — is *legitimate* and carries
meaning: it is the abstention signature agreed for D13. See ``is_abstention``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Confidence bounds on the pipeline's **output** contract, fixed by the assignment.
CONFIDENCE_MIN, CONFIDENCE_MAX = 0.0, 1.0

#: Confidence bound on the **intermediate** scale the model is prompted for.
RAW_CONFIDENCE_MAX = 100.0

#: Confidence at or below this value, combined with no supporting evidence, marks a
#: record as "nothing assessable in the note" rather than "assessed as Non-PD".
#: Fixed by the D13 decision. Expressed on the output scale; the intermediate
#: equivalent is derived rather than written twice.
ABSTENTION_CONFIDENCE_CEILING = 0.2
RAW_ABSTENTION_CONFIDENCE_CEILING = ABSTENTION_CONFIDENCE_CEILING * RAW_CONFIDENCE_MAX


class Classification(StrEnum):
    """The two permitted labels. Values are the exact strings the schema requires."""

    PD = "PD"
    NON_PD = "Non-PD"


class _ClassificationBase(BaseModel):
    """Fields and rules common to both contracts. The confidence bound differs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Ceiling below which an evidence-free Non-PD counts as an abstention.
    #: Overridden per scale by the subclasses. Must be a ClassVar: a plain
    #: annotated attribute would become a Pydantic field, and a leading-underscore
    #: one becomes a ModelPrivateAttr rather than the float it looks like.
    ABSTENTION_CEILING: ClassVar[float] = ABSTENTION_CONFIDENCE_CEILING

    classification: Classification
    confidence_score: float
    supporting_evidence: list[str] = Field(default_factory=list)
    clinical_reasoning: str = Field(min_length=1)

    @model_validator(mode="after")
    def _pd_requires_evidence(self):
        if self.classification is Classification.PD and not self.supporting_evidence:
            raise ValueError(
                "classification 'PD' requires at least one supporting_evidence quote; "
                "asserting progression with no quote from the note is unsupported by "
                "construction"
            )
        return self

    @model_validator(mode="after")
    def _evidence_quotes_are_non_empty(self):
        for i, quote in enumerate(self.supporting_evidence):
            if not quote.strip():
                raise ValueError(f"supporting_evidence[{i}] is empty or whitespace only")
        return self

    @property
    def is_abstention(self) -> bool:
        """True when this record means "no assessable content", not "assessed Non-PD".

        The D13 signature: a ``Non-PD`` label with no evidence and a confidence at or
        below the ceiling for this scale. Machine-detectable by design, so the
        pipeline can route these to a clinician instead of reporting them as
        negative findings.
        """
        return (
            self.classification is Classification.NON_PD
            and not self.supporting_evidence
            and self.confidence_score <= type(self).ABSTENTION_CEILING
        )


class RawClassification(_ClassificationBase):
    """Stage 2's output. Confidence on the 0–100 scale the prompts ask for."""

    ABSTENTION_CEILING: ClassVar[float] = RAW_ABSTENTION_CONFIDENCE_CEILING

    confidence_score: float = Field(ge=0.0, le=RAW_CONFIDENCE_MAX)

    def to_output(self) -> ClinicalClassification:
        """Convert to the assignment's output contract, rescaling confidence to 0.0–1.0.

        The single crossing point between the two scales. Keeping it here means a
        0–100 value cannot reach a metric expecting a probability — the bug class
        that drove ROC-AUC to 0.079 in an earlier revision of Part 3.2.
        """
        return ClinicalClassification(
            classification=self.classification,
            confidence_score=self.confidence_score / RAW_CONFIDENCE_MAX,
            supporting_evidence=list(self.supporting_evidence),
            clinical_reasoning=self.clinical_reasoning,
        )


class ClinicalClassification(_ClassificationBase):
    """The pipeline's output. Matches the assignment's 2.3 schema exactly."""

    ABSTENTION_CEILING: ClassVar[float] = ABSTENTION_CONFIDENCE_CEILING

    confidence_score: float = Field(ge=CONFIDENCE_MIN, le=CONFIDENCE_MAX)


#: Field names the prompts describe to the model. Kept here so a test can assert
#: the prose schema block in ``src/prompts`` has not drifted from these models.
SCHEMA_FIELD_NAMES: tuple[str, ...] = tuple(ClinicalClassification.model_fields)
