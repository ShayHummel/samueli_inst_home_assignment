# Part 1 — Architecture & Validation

---

## Q1.1 — On-prem model selection

*Context: oncology records are highly sensitive; no data may leave the hospital network,
so every model runs fully offline on our own hardware. The workload is mixed — high-volume
field extraction plus a smaller set of hard reasoning cases.*

### a) Compare three open-weight models you would deploy locally. For each: strengths, weaknesses, and the clinical use case it is best suited to.

**Answer:**

**Deployment thesis.** The workload has two tiers, so the right answer is not a single
model. I would deploy a mid-size multilingual model for the high-volume extraction tier
and escalate the smaller set of hard cases to a large reasoning model. The three models
below encode that as two competing hypotheses for the escalation tier:

| Model | Strengths | Weaknesses | Best-suited clinical use case |
| --- | --- | --- | --- |
| **Qwen3.5-27B**<br>*extraction tier* | Broad multilingual coverage — the main reason to evaluate it on mixed Hebrew/English notes; manageable 27B footprint; long context; serves structured extraction efficiently under local serving (vLLM / TGI). | Dense inference is less compute-efficient per parameter than a similarly sized MoE; broad multilingual ability is not evidence of Hebrew *clinical* competence. | High-volume field extraction: diagnoses, treatments, dates, response status and other structured fields. |
| **gpt-oss-120b**<br>*reasoning tier* | Strong reasoning and instruction-following; configurable reasoning effort; native structured-output support; Apache 2.0. 117B total parameters but only ~5.1B active, so it fits a single 80 GB GPU — a genuinely large reasoning model that is practical on-prem. | Slower and heavier than the extraction tier, so it is worth reserving for escalated cases only; text-only. | Ambiguous clinical reasoning escalated from the extraction tier: temporality, negation, conflicting evidence, hard PD / Non-PD calls. |
| **Nemotron 3 Super 120B-A12B**<br>*reasoning tier alternative* | Strong reasoning; efficient MoE (~12B active of 120B); switchable reasoning / non-reasoning modes; very long context; NVIDIA-optimised serving stack, which matters if the hospital is already NVIDIA-heavy. | Needs materially more GPU than gpt-oss in its documented BF16 configuration; Hebrew is not an officially supported language; general / agentic rather than clinically specialised. | Long-context and RAG-heavy cases: reasoning across lengthy records or retrieved evidence. The throughput-oriented alternative to gpt-oss. |

**A caveat that applies to all three, not to any one of them.** None has established Hebrew
*clinical* performance. That is a property of the current open-weight landscape rather than a
distinguishing weakness of a particular model, so I treat it once here and address the
mitigation in (b).

**Selection is empirical, not a priori.** These are candidates, not a final choice. Selection
should rest on a hospital-specific benchmark over de-identified Hebrew/English oncology notes,
measuring extraction and classification quality, faithfulness, JSON schema adherence, latency,
throughput and GPU memory. Public general-purpose benchmarks are useful for shortlisting
candidates but are not sufficient evidence for clinical deployment.

### b) Hebrew clinical text: what concern do most open models raise, and how would you handle it?

**Answer:**
Most open-weight LLMs are trained predominantly on English, with substantially less Hebrew—and even less Hebrew clinical text. Hebrew is morphologically rich, making tokenization harder, and Israeli clinical notes commonly combine Hebrew with English medical terminology, transliterations, abbreviations, drug names, and non-standard shorthand. Consequently, good English or general multilingual benchmark performance cannot be assumed to transfer to Hebrew clinical extraction. Hebrew-specific NLP work has identified morphology and tokenization as a challenge, while prior clinical NLP research found that handling transliterated medical terms substantially improves Hebrew medical information extraction.

**Mitigation:** I would first benchmark candidate models on a clinician-annotated, representative Hebrew oncology test set, stratified by language characteristics (Hebrew-only vs. Hebrew-English code-switching, abbreviations, transliteration). I would measure both task accuracy and failure patterns rather than relying on generic multilingual benchmarks. If performance is insufficient, I would evaluate continued pre-training and domain adaptation on de-identified local clinical text and supervised fine-tuning on the target extraction tasks, while maintaining a fixed Hebrew clinical holdout set. Recent Hebrew clinical NLP research provides evidence this direction is viable: a Hebrew medical model continually pre-trained on >5M de-identified hospital records reported strong results on clinical temporal extraction, including an oncology dataset (https://arxiv.org/abs/2512.11502).

---

## Q1.2 — Validation strategy

*Assume the pipeline outputs both extracted fields and a binary label.*

### a) Detail three different methodology frameworks for validating the LLM's output. For each, state what it catches and what it misses.

**Answer:**

| Framework | Method | Catches | Misses |
| --- | --- | --- | --- |
| **Human gold-standard evaluation** | Compare model outputs against an independently clinician-annotated, adjudicated test set. | Clinical errors, negation and temporality mistakes, clinically meaningful misinterpretations. | Limited sample size, being cost-bound, so rare cases may be underrepresented. |
| **Consistency & robustness testing** | Repeated runs, controlled input perturbations, and disagreement across independent model families. | Instability, prompt sensitivity, brittle behaviour, and which cases are genuinely difficult. | Agreement does not imply correctness — models may share systematic errors. |
| **Automated reference-based validation** | Exact and normalised matching for structured fields, schema and range checks, evidence verification, and semantic similarity where appropriate. | Scalable detection of incorrect, malformed or unsupported outputs. | Rules cannot capture all clinical context; semantic similarity does not guarantee clinical correctness. |

These are complementary rather than competing: human evaluation establishes correctness,
robustness testing identifies instability, and automated validation makes evaluation
possible at scale.

### b) Annotation strategy — design a Human-in-the-Loop (HITL) framework using clinical experts to build your gold standard.

Must cover:
- how many notes, and annotated by whom;
- how you would measure agreement (**name the statistical metric for inter-rater reliability**);
- what happens when two clinicians disagree;
- the metrics you would use for model-vs-human performance.

**Answer:**

- **Sample size & annotators:** A representative gold-standard set of approximately 500–1,000
  notes, stratified by relevant characteristics such as label, note type, language and
  known-difficult clinical cases. Two clinicians annotate each note independently, working
  from explicit written annotation guidelines and following a calibration phase.
- **Agreement metric:** Cohen's κ for the categorical label, or Fleiss' κ where three or more
  raters annotate the same notes.
- **Disagreement resolution:** Disagreements are adjudicated by a third, senior clinician,
  whose decision defines the gold label.
- **Model-vs-human metrics:** Precision, recall, F1 and the confusion matrix for the binary
  label; exact and normalised match for the extracted fields — all measured against the
  adjudicated gold standard.

### c) Which metrics would you report for the binary label, and when is ROC-AUC misleading? If the positive class has ~5% prevalence, what do you report instead?

**Answer:**

I would report precision, recall (sensitivity), specificity, F1, the confusion matrix,
ROC-AUC and PR-AUC.

ROC-AUC becomes misleading under severe class imbalance, because the large number of
negatives means a low false-positive *rate* can still correspond to a clinically significant
absolute number of false positives. At approximately 5% positive prevalence, accuracy is
likewise uninformative: labelling every case negative already scores 95%.

I would therefore emphasise precision, recall, F1 and PR-AUC, with particular attention to
recall wherever false negatives carry high clinical cost.

### d) What is "LLM-as-a-judge"? Give two concrete risks and a mitigation for each. How would you decide whether the judge itself can be trusted?

**Answer:**

- **Definition:** LLM-as-a-judge uses an LLM to evaluate another model's output against a
  predefined rubric — for example, deciding whether an extraction is clinically correct, or
  whether it is actually supported by the source note.
- **Risk 1 — systematic / correlated errors:** the judge may share the same misconceptions as
  the model it evaluates. *Mitigation:* use a different model family, and validate the judge's
  decisions against clinician annotations.
- **Risk 2 — prompt, order and style sensitivity:** judgments may change because of
  presentation, verbosity or ordering rather than correctness. *Mitigation:* a standardised
  rubric, deterministic decoding, randomised ordering, and explicit robustness tests.
- **Trusting the judge:** the judge must itself be validated against clinician judgments on a
  representative gold-standard subset, measuring agreement and explicitly analysing the
  disagreements. A larger or stronger model should not automatically be considered a reliable
  judge.

### e) Faithfulness: propose a concrete method to detect when an extracted value is not actually supported by the source note, and how you would quantify this across a dataset.

**Answer:**

I would require every extracted value to carry an exact supporting quote or span from the
source note:

`field → extracted value → supporting evidence`

Validation then runs in two stages. First, programmatically verify that the evidence span
actually appears in the source note. Second, verify that the span genuinely supports the
extracted value — using deterministic normalisation and rules where possible, and a
separately validated entailment or judge model for the harder cases.

Across the dataset I would report:

> **Evidence-supported extraction rate** = supported extracted fields / all extracted fields

I would additionally put a sample through clinician review, weighted towards unsupported and
clinically high-risk extractions.

### f) You measure F1 = 0.92 on your held-out test set, yet clinicians report the system is unreliable in production. Give at least four plausible causes and one diagnostic step for each.

**Answer:**

| # | Plausible cause | Diagnostic step |
| --- | --- | --- |
| 1 | Small or unrepresentative test set, particularly too few positive cases. | Inspect positive-class sample size and compute bootstrap confidence intervals. |
| 2 | Train–test leakage: notes from the same patients or templates on both sides of the split. | Re-evaluate under patient-level and temporal splits. |
| 3 | Production distribution shift. | Compare test vs. production distributions and evaluate a recent production sample. |
| 4 | Aggregate F1 hides subgroup failures. | Stratify performance by language (Hebrew / English / mixed), note type, department and time period. |
| 5 | F1 does not capture clinical severity — errors are not equally costly. | Clinician error analysis categorised by error type and clinical consequence, especially false negatives. |
| 6 | Failures outside the LLM: truncation, parsing, preprocessing or retrieval. | Trace production cases end to end — raw note → prompt → raw model output → parser → stored result. |

A high aggregate F1 is therefore insufficient evidence of clinical reliability. Validation
should include confidence intervals, subgroup analysis, temporal and external validation,
clinically weighted error analysis, and end-to-end production monitoring.

---

## AI assistance disclosure

