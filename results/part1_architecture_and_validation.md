# Part 1 — Architecture & Validation

<!-- ---------------------------------------------------------------------------
COMMENTS TO CLAUDE

Mark feedback inline, next to whatever it refers to, in this form:

    > **@claude:** rewrite this cell, it repeats the row above

I action each one and delete the marker once done, so an empty grep means
everything has been handled:

    grep -n '@claude' results/*.md

These HTML comment blocks do not render, so they stay out of the submitted PDF.
---------------------------------------------------------------------------- -->

---

## Q1.1 — On-prem model selection

*Context: oncology records are highly sensitive; no data may leave the hospital network,
so every model runs fully offline on our own hardware. The workload is mixed — high-volume
field extraction plus a smaller set of hard reasoning cases.*

### a) Compare three open-weight models you would deploy locally. For each: strengths, weaknesses, and the clinical use case it is best suited to.

**Deployment thesis.** The workload has two tiers, so the right answer is not a single
model.

I would deploy a mid-size multilingual model for the high-volume extraction tier
and escalate the smaller set of hard cases to a large reasoning model. The three models
below encode that as two competing hypotheses for the escalation tier:

| Model | Strengths | Weaknesses | Best-suited clinical use case |
| --- | --- | --- | --- |
| **Qwen3.5-27B**<br>*extraction tier*<br>Licence: `Apache 2.0`<br>Precision: BF16 ≈54 GB → FP8 ≈27 GB | • Broad multilingual coverage — the reason to evaluate it on Hebrew/English notes<br>• Manageable 27B footprint<br>• Long context<br>• Serves structured extraction efficiently (vLLM / TGI) | • Dense: less compute-efficient per parameter than a similarly sized MoE<br>• Not the accuracy ceiling — hard negation and temporality cases must be escalated, not solved here | High-volume field extraction: diagnoses, treatments, dates, response status and other structured fields. |
| **gpt-oss-120b**<br>*reasoning tier*<br>Licence: `Apache 2.0`<br>Precision: ships natively MXFP4, ≈80 GB → 1 GPU | • Strong reasoning and instruction-following<br>• Configurable reasoning effort<br>• Native structured-output support<br>• 117B total but only ~5.1B active — a genuinely large reasoning model that is practical on-prem | • Slower and heavier than the extraction tier — reserve for escalated cases only<br>• Text-only | Ambiguous clinical reasoning escalated from the extraction tier: temporality, negation, conflicting evidence, hard PD / Non-PD calls. |
| **Nemotron 3 Super 120B-A12B**<br>*reasoning tier alternative*<br>Licence: `NVIDIA Open Model Licence`<br>Precision: BF16 ≈240 GB → 4×80 GB; FP8 ≈120 GB → 2×80 GB | • Strong reasoning<br>• Efficient MoE — ~12B active of 120B<br>• Switchable reasoning / non-reasoning modes<br>• Very long context<br>• NVIDIA-optimised serving stack — matters if the hospital is already NVIDIA-heavy | • Needs 2–4× the GPUs of gpt-oss at comparable precision<br>• Hebrew is not an officially supported language<br>• General / agentic rather than clinically specialised | Long-context and RAG-heavy cases: reasoning across lengthy records or retrieved evidence. The throughput-oriented alternative to gpt-oss. |

**A caveat that applies to all three, not to any one of them.** Declared language support
differs between them — hence Nemotron's row — but *clinical* Hebrew performance is unestablished
for all three. That is a property of the current open-weight landscape rather than a
distinguishing weakness of any one model, so it is stated once here rather than repeated per
row, and the mitigation is in (b).

*Licence constraints:* on-prem terms are
load-bearing, and "open-weight" does not mean unrestricted. Llama is the standard example — its
community licence carries acceptable-use terms and a monthly-active-user threshold above which
separate permission from Meta is required, so it needs legal sign-off in a way Apache 2.0 does
not. A restrictive or non-commercial licence can therefore disqualify a model regardless of how
it benchmarks, which is why the licence sits in the table beside the technical properties.

### b) Hebrew clinical text: what concern do most open models raise, and how would you handle it?

**Concern.** Open-weight LLMs are trained overwhelmingly on English, with far less Hebrew and
less still Hebrew *clinical* text. Hebrew's rich morphology complicates tokenization, and
Israeli oncology notes code-switch constantly: Hebrew prose around English drug names,
transliterated terms, abbreviations and ad-hoc shorthand. Strong English or general
multilingual scores therefore cannot be assumed to transfer — Hebrew NLP work identifies
morphology and tokenization as the core difficulty, and clinical NLP work shows that handling
transliterated medical terms materially improves Hebrew extraction.

**Mitigation.** Benchmark candidates on a clinician-annotated Hebrew oncology set stratified by
language profile (Hebrew-only vs. code-switched, abbreviation- and transliteration-heavy),
scoring failure patterns alongside accuracy rather than trusting generic multilingual
benchmarks. If that falls short, continue pre-training on de-identified local clinical text and
fine-tune on the target extraction tasks, against a fixed Hebrew clinical holdout. The
direction is evidenced: a Hebrew medical model continually pre-trained on >5M de-identified
hospital records reported strong clinical temporal extraction, including on an oncology dataset
([arXiv:2512.11502](https://arxiv.org/abs/2512.11502)).

---

## Q1.2 — Validation strategy

*Assume the pipeline outputs both extracted fields and a binary label.*

### a) Detail three different methodology frameworks for validating the LLM's output. For each, state what it catches and what it misses.

| Framework | Method | Catches | Misses | Mitigation |
| --- | --- | --- | --- | --- |
| **Human gold-standard evaluation** | Compare model outputs — **both the binary label and the extracted fields** — against an independently clinician-annotated, adjudicated test set. | Clinical errors, negation and temporality mistakes, clinically meaningful misinterpretations. | • Cost-bound sample size, so rare cases are underrepresented<br>• Free-text extractions vary in wording and span boundaries, so they do not compare to a human annotation by exact match | • Stratify and oversample the rare and hard strata rather than sampling uniformly; report confidence intervals so a small *n* stays visible<br>• Score spans by normalised and partial-overlap matching (character-offset IoU — positional, not lexical; see (b) on ROUGE), reserving exact match for closed-vocabulary fields — supplied by the automated framework below |
| **Consistency & robustness testing** | Repeated runs, controlled input perturbations, and disagreement across independent model families. | Instability, prompt sensitivity, brittle behaviour, and which cases are genuinely difficult. | Agreement does not imply correctness — models may share systematic errors. | Anchor a subset to the human gold standard so agreement is calibrated against truth, and draw the ensemble from genuinely independent model families rather than checkpoints of one lineage. |
| **Automated reference-based validation** | Exact and normalised matching for structured fields, schema and range checks, evidence verification, and semantic similarity where appropriate. | Scalable detection of incorrect, malformed or unsupported outputs — including the span-variance problem above, via normalised and partial-overlap scoring. | Rules cannot capture all clinical context; semantic similarity does not guarantee clinical correctness. | Treat automated scores as a screen, not a verdict: route low-scoring and disagreeing cases to clinician review, and periodically re-validate the automated metrics against the gold standard. |

These are complementary rather than competing: human evaluation establishes correctness,
robustness testing identifies instability, and automated validation makes evaluation possible
at scale. Notably, the mitigations are largely *each other* — the span-variance limit of human
comparison is answered by automated partial-overlap scoring, and the correctness blind spot of
automated scoring is answered by anchoring back to the gold standard. No one framework is
sufficient alone.

### b) Annotation strategy — design a Human-in-the-Loop (HITL) framework using clinical experts to build your gold standard.

- **Sample size & annotators:** A representative gold-standard set of approximately 500–1,000
  notes, stratified by relevant characteristics such as label, note type, language and
  known-difficult clinical cases. Two clinicians annotate each note independently, working
  from explicit written annotation guidelines and following a calibration phase.
- **Agreement metric:** Cohen's κ for the categorical label, or Fleiss' κ where three or more
  raters annotate the same notes. κ is the right instrument for a fixed-category label, but
  span-level agreement on the *extracted fields* is not a κ problem — there is no fixed
  category set and no well-defined negative class. For those I would report pairwise F1 between
  annotators over spans, or Krippendorff's α where annotators skip items or the number of
  raters varies between notes.
- **Disagreement resolution:** Disagreements are adjudicated by a third, senior clinician,
  whose decision defines the gold label.
- **Model-vs-human metrics:** Precision, recall, F1 and the confusion matrix for the binary
  label. For the extracted fields the metric has to match the field type: exact match after
  normalisation for categorical fields; terminology- or ISO-normalised match for drugs,
  diagnoses and dates, so that "Taxol" against "paclitaxel" is not scored as a miss; and
  character-offset partial-match precision / recall / F1 for evidence spans, as used in the
  i2b2 / n2c2 clinical IE tasks. All measured against the adjudicated gold standard.
- **On ROUGE:** worth including, but scoped. It earns a place as a *secondary* metric for
  genuinely free-text fields — a narrative reasoning field, say — and then only as ROUGE-L
  **F-measure**, since plain ROUGE-N is recall-oriented and therefore rewards verbose
  over-extraction. It should not become the headline extraction metric here, for two reasons.
  First, it is negation-blind: "no evidence of progression" and "evidence of progression" share
  most of their unigrams while being clinically opposite, which is precisely the failure mode
  this pipeline exists to catch. Second, it ignores position, so it cannot distinguish a quote
  taken from the right part of the note from lexically similar text elsewhere — which is why
  (a) scores spans by character offset rather than by lexical overlap.
- **Interpretation:** report these **against inter-annotator agreement, not against 1.0.** If
  two clinicians agree on only 85 of 100 notes, the 15 they dispute have no single right answer
  — the adjudicator merely picked one defensible reading. A model at 0.83 is then at the task's
  ceiling, not 17 points from solved. Without that reference line, F1 suggests far more room for
  improvement than actually exists, and it misdirects effort: at the ceiling, gains come from
  sharpening the annotation guidelines, not from a better model.

### c) Which metrics would you report for the binary label, and when is ROC-AUC misleading? If the positive class has ~5% prevalence, what do you report instead?

I would report precision (PPV), recall (sensitivity), specificity, F1, the confusion matrix,
ROC-AUC and PR-AUC.

**Why specificity, given the imbalance.** Only for one reason, and with a caveat attached.
Clinicians read diagnostic performance as a sensitivity/specificity pair, so omitting it makes
the report harder for the people who have to act on it. But under ~5% prevalence specificity is
reassuring and nearly uninformative: it is 1 − FPR, so it shares exactly the weakness that
makes ROC-AUC misleading here, and a model can post 0.95 specificity while generating more
false positives than true positives. Precision (PPV) is the operationally meaningful
counterpart, because it is what determines how much of a clinician's review queue is noise. So
I report specificity for communication, and lead on PPV for decisions.

ROC-AUC becomes misleading under severe class imbalance, because the large number of
negatives means a low false-positive *rate* can still correspond to a clinically significant
absolute number of false positives. At approximately 5% positive prevalence, accuracy is
likewise uninformative: labelling every case negative already scores 95%.

I would therefore emphasise precision, recall, F1 and PR-AUC, with particular attention to
recall wherever false negatives carry high clinical cost.

Two reporting disciplines matter as much as the choice of metric. First, precision, recall and
F1 are all **threshold-dependent**, so I would fix and state an explicit operating threshold —
chosen on validation data against the clinical cost ratio of a false negative to a false
positive, not left at a default of 0.5 — and report the point metrics at that threshold
alongside the threshold-free AUCs. Second, **PR-AUC is prevalence-dependent**: its baseline is
the positive rate itself, so PR-AUC values are not comparable across datasets, sites or time
periods with different prevalence. I would always report prevalence next to it.

### d) What is "LLM-as-a-judge"? Give two concrete risks and a mitigation for each. How would you decide whether the judge itself can be trusted?

- **Definition:** LLM-as-a-judge uses an LLM to evaluate another model's output against a
  predefined rubric — for example, deciding whether an extraction is clinically correct, or
  whether it is actually supported by the source note.
- **Risk 1 — systematic / correlated errors:** the judge may share the same misconceptions as
  the model it evaluates. *Mitigation:* use a different model family, and validate the judge's
  decisions against clinician annotations.
- **Risk 2 — prompt, order and style sensitivity:** judgments may change because of
  presentation, verbosity or ordering rather than correctness. *Mitigation:* a standardised
  rubric, deterministic decoding, randomised ordering, and explicit robustness tests.
- **Trusting the judge:** the judge is just another model under evaluation, so it must itself
  be validated against clinician judgments on a representative gold-standard subset.
  Concretely, I would measure judge-vs-clinician agreement with Cohen's κ and compare it
  against the **human-human κ on the same items**: a judge that agrees with clinicians about as
  well as clinicians agree with each other is usable, while one materially below that ceiling
  is not — regardless of its size. I would also analyse the disagreements explicitly rather
  than reporting only the aggregate, and would trust the judge only over the case distribution
  on which it was validated. A larger or stronger model should not automatically be considered
  a reliable judge.

### e) Faithfulness: propose a concrete method to detect when an extracted value is not actually supported by the source note, and how you would quantify this across a dataset.

I would require every extracted value to carry an exact supporting quote or span from the
source note:

`field → extracted value → supporting evidence`

Validation then runs in two stages. The two stages fail in *different* ways, so I would keep
their counts separate rather than collapsing them into a single number:

1. **Span presence** — programmatically verify the evidence span actually appears in the source
   note, after normalising whitespace, casing and punctuation. Without that normalisation,
   exact matching produces false failures on quotes that were merely re-wrapped or re-cased. A
   span that is genuinely absent means the model **fabricated its own evidence**.
2. **Span support** — verify the span actually entails the extracted value, using deterministic
   normalisation and rules where possible and a separately validated entailment or judge model
   for the harder cases. A span that is present but does not entail the value means the
   evidence is real but the **inference drawn from it is unsupported**.

The distinction is worth the extra bookkeeping because the remedies differ: fabricated evidence
is a grounding failure, addressed by constrained decoding and forcing verbatim span copying,
whereas unsupported inference is a reasoning failure, addressed by prompt and model changes.

Across the dataset I would report:

> **Evidence-supported extraction rate** = supported extracted fields / all extracted fields

broken down by the two failure modes above and by field, since some fields are systematically
harder to ground than others. I would additionally put a sample through clinician review,
weighted towards unsupported and clinically high-risk extractions.

### f) You measure F1 = 0.92 on your held-out test set, yet clinicians report the system is unreliable in production. Give at least four plausible causes and one diagnostic step for each.

| # | Plausible cause | Diagnostic step |
| --- | --- | --- |
| 1 | Small or unrepresentative test set, particularly too few positive cases. | Inspect positive-class sample size and compute bootstrap confidence intervals. |
| 2 | Train–test leakage: notes from the same patients or templates on both sides of the split. | Re-evaluate under patient-level and temporal splits. |
| 3 | Production distribution shift. | Compare test vs. production distributions and evaluate a recent production sample. |
| 4 | Aggregate F1 hides subgroup failures. | Stratify performance by language (Hebrew / English / mixed), note type, department and time period. |
| 5 | F1 does not capture clinical severity — errors are not equally costly. | Clinician error analysis categorised by error type and clinical consequence, especially false negatives. |
| 6 | Failures outside the LLM: truncation, parsing, preprocessing or retrieval. | Trace production cases end to end — raw note → prompt → raw model output → parser → stored result. |
| 7 | Human factors rather than model quality: output is surfaced without its supporting evidence or confidence, so clinicians cannot verify a result and withhold trust even when it is correct. | Observe clinicians using the system and interview them on what they would need in order to accept a result; measure how often they override outputs that were in fact correct. |
| 8 | Test-set label noise. F1 measures agreement with the gold standard, so if the gold labels are themselves wrong, the metric is confidently measuring the wrong target. | Re-adjudicate a random sample of test labels with a senior clinician and report inter-annotator agreement on the test set itself. |

A high aggregate F1 is therefore insufficient evidence of clinical reliability. Validation
should include confidence intervals, subgroup analysis, temporal and external validation,
clinically weighted error analysis, and end-to-end production monitoring.

---

## AI assistance disclosure

