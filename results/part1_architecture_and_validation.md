# Part 1 — Architecture & Validation

> Theoretical. Concise, well-reasoned answers are preferred over long ones.

Suggested length is noted per answer as a guide only — trim or extend as the point requires.

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

*(~4–6 sentences: name the concern, then the concrete mitigation.)*

**Answer:**

---

## Q1.2 — Validation strategy

*Assume the pipeline outputs both extracted fields and a binary label.*

### a) Detail three different methodology frameworks for validating the LLM's output. For each, state what it catches and what it misses.

*(~3 blocks. The "what it misses" half is where the marks are — keep it explicit.)*

**Answer:**

1. **TBD** — *Catches:* … *Misses:* …
2. **TBD** — *Catches:* … *Misses:* …
3. **TBD** — *Catches:* … *Misses:* …

### b) Annotation strategy — design a Human-in-the-Loop (HITL) framework using clinical experts to build your gold standard.

Must cover:
- how many notes, and annotated by whom;
- how you would measure agreement (**name the statistical metric for inter-rater reliability**);
- what happens when two clinicians disagree;
- the metrics you would use for model-vs-human performance.

*(~8–12 sentences, or four short labelled paragraphs matching the four bullets.)*

**Answer:**

- **Sample size & annotators:**
- **Agreement metric:**
- **Disagreement resolution:**
- **Model-vs-human metrics:**

### c) Which metrics would you report for the binary label, and when is ROC-AUC misleading? If the positive class has ~5% prevalence, what do you report instead?

*(~5–7 sentences. Three distinct sub-answers — make sure all three are visibly answered.)*

**Answer:**

### d) What is "LLM-as-a-judge"? Give two concrete risks and a mitigation for each. How would you decide whether the judge itself can be trusted?

*(~6–9 sentences. The last sub-question — validating the validator — is the discriminating one.)*

**Answer:**

- **Definition:**
- **Risk 1 + mitigation:**
- **Risk 2 + mitigation:**
- **Trusting the judge:**

### e) Faithfulness: propose a concrete method to detect when an extracted value is not actually supported by the source note, and how you would quantify this across a dataset.

*(~5–8 sentences. "Concrete" is doing work in the question — name the mechanism, and give the dataset-level metric a name and a denominator.)*

**Answer:**

### f) You measure F1 = 0.92 on your held-out test set, yet clinicians report the system is unreliable in production. Give at least four plausible causes and one diagnostic step for each.

*(Four+ cause/diagnostic pairs. Aim for causes from genuinely different families — data, metric,
deployment, human-factors — rather than four flavours of the same one.)*

**Answer:**

| # | Plausible cause | Diagnostic step |
| --- | --- | --- |
| 1 | *TBD* | |
| 2 | *TBD* | |
| 3 | *TBD* | |
| 4 | *TBD* | |

---

## AI assistance disclosure

*(Per the assignment's Logistics section. To be completed before submission.)*
