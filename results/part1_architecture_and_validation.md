# Part 1 — Architecture & Validation

> Theoretical. Concise, well-reasoned answers are preferred over long ones.

Suggested length is noted per answer as a guide only — trim or extend as the point requires.

---

## Q1.1 — On-prem model selection

*Context: oncology records are highly sensitive; no data may leave the hospital network,
so every model runs fully offline on our own hardware. The workload is mixed — high-volume
field extraction plus a smaller set of hard reasoning cases.*

### a) Compare three open-weight models you would deploy locally. For each: strengths, weaknesses, and the clinical use case it is best suited to.

*(~3 short blocks, or a table. Note the tie-back to the mixed workload: which model serves
the high-volume extraction tier vs. the hard-reasoning tier.)*

**Answer:**

| Model | Strengths | Weaknesses | Best-suited clinical use case |
| --- | --- | --- | --- |
| *TBD* | | | |
| *TBD* | | | |
| *TBD* | | | |

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
