# Part 4 — Embeddings & Vector Search

<!-- ---------------------------------------------------------------------------
COMMENTS TO CLAUDE

Mark feedback inline, next to whatever it refers to, in this form:

    > **@claude:** rewrite this, it repeats the point above

Use `@claude` and nothing else — a different marker will be missed by the sweep:

    grep -n '@claude' results/*.md

These HTML comment blocks do not render, so they stay out of the submitted PDF.
---------------------------------------------------------------------------- -->

---

**Scenario.** Semantic search across millions of clinical notes, plus a RAG layer to support
extraction on hard cases. Fully on-prem, per Part 1.

---

## E.1 — Which embedding models would you evaluate, and how would you decide?

### The central tension

There is no single model that is both best-in-class for clinical text *and* competent in
Hebrew. The strongest clinical embedders are English-only; the strongest Hebrew-capable
embedders are general-domain. That trade-off, not a leaderboard, is what determines the
architecture — so I would name it up front rather than pick a model and discover it later.

### Candidates

Ordered by role, most promising for this task to least.

| Model                                  | Role                    | Type                  | Strengths                                                                                                                                                                                                              | Weaknesses                                                                                                                                                                                              |
|----------------------------------------|-------------------------|-----------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **BGE-M3**                             | **Primary retriever**   | General, multilingual | Broad multilingual coverage including Hebrew; 8,192-token context, so whole notes fit unchunked; emits **dense + sparse + multi-vector** from one model, giving lexical and semantic retrieval without a second system | General-domain: no clinical supervision; larger and slower than single-signal encoders                                                                                                                  |
| **Qwen3-Embedding** (0.6B / 4B / 8B)   | **Co-primary**          | General, multilingual | Hebrew in scope via Qwen3's multilingual training; 32k context; instruction-aware queries; Matryoshka dimensions; Apache 2.0                                                                                           | Dense only, so no sparse channel; the 8B tier is expensive at corpus scale                                                                                                                              |
| **BM25**                               | **Mandatory baseline**  | Lexical               | No training, no GPU, no drift; unbeatable on exact drug names, ICD codes, identifiers                                                                                                                                  | No semantics; misses paraphrase                                                                                                                                                                         |
| **multilingual-E5** (large / instruct) | Neural baseline to beat | General, multilingual | Strong, well-established multilingual baseline; cheap to serve                                                                                                                                                         | Requires `query:` / `passage:` prefixes — omit them and quality degrades sharply, a real operational footgun; 512-token limit on base variants forces chunking                                          |
| **GTE-multilingual**                   | Throughput alternative  | General, multilingual | 8,192 context, notably smaller and faster than BGE-M3                                                                                                                                                                  | Fewer retrieval signals; less battle-tested clinically                                                                                                                                                  |
| **BioLORD-2023**                       | Shortlist reranker      | Domain, English       | Trained against ontology *definitions* rather than co-occurrence, so clinically distinct concepts stay far apart instead of collapsing because they appear in the same notes; strong on biomedical sentence similarity | Sentence-scale, not document-scale; English only                                                                                                                                                        |
| **SapBERT**                            | Concept normalization   | Domain, English       | Self-aligned over UMLS synonyms; excellent at mapping surface forms to concepts (`MI` ↔ `myocardial infarction`)                                                                                                       | An **entity linker, not a passage retriever** — tuned for short strings, not documents; English only                                                                                                    |
| **MedCPT**                             | Literature corpus only  | Domain, English       | Trained on ~255M PubMed query–article click pairs, so it is a genuine *retriever* rather than a repurposed encoder; strong biomedical relevance                                                                        | Trained on **PubMed abstracts, not clinical notes** — academic prose differs sharply from telegraphic EHR text full of abbreviations; English only                                                      |
| **PubMedBERT** embeddings              | Not deployable as-is    | Domain, English       | Pretrained from scratch on PubMed, so the vocabulary is genuinely biomedical rather than a general model's word-pieces                                                                                                 | **Masked-LM pretraining alone is weak for retrieval** — it needs contrastive fine-tuning before its embeddings rank usefully, so a checkpoint is an encoder to fine-tune, not a retriever; English only |

### The architecture this implies

**1. BGE-M3 against Qwen3-Embedding is the real bake-off.** Multilingual coverage is
non-negotiable given the Hebrew/English mix, and both clear it with room for whole notes
unchunked — no note in `Oncology.csv` exceeds ~2,000 tokens. They differ on one axis that
matters here: BGE-M3 emits a **sparse** signal alongside the dense one, and clinical text turns
on rare tokens (drug names, ICD codes, `s/p`, `PR`) that dense embeddings smooth away. Qwen3 is
dense only, so matching those needs BM25 beside it — a second system to tune. Against that,
Qwen3 offers instruction-aware queries and Matryoshka dimensions, which let index size be
traded against accuracy *without re-embedding the corpus* — worth real money at the scale where
re-embedding is a multi-day job. I would start from BGE-M3 for the single-system sparse+dense
story and treat Qwen3 as the one candidate genuinely likely to beat it.

**2. The domain models each do one job, and none of them is first-stage retrieval.** SapBERT
normalizes entity mentions to UMLS concept unique identifiers (CUIs) — stable IDs such
as `C0030567` for Parkinson's disease that gather every surface form of one concept — so `MI`, `myocardial infarction` and the Hebrew
equivalent collapse to one concept; those CUIs become *metadata* (see E.2) and feed the sparse
channel. BioLORD-2023 reranks a shortlist, where definition-grounded training separates concepts
that co-occurrence-trained models conflate. MedCPT belongs on a literature corpus, not on EHR
notes. PubMedBERT is an encoder to fine-tune, not a retriever to deploy. Using any of them as
the primary retriever is a category error — the failure mode is picking a model because "Med" or
"Bio" appears in its name.

**3. BM25 as the floor, run first.** On clinical corpora a lexical baseline is often
embarrassingly competitive, because much clinical retrieval is known-item search for a named
drug or code. If a neural retriever cannot beat BM25 on our own queries, that is a finding, not
a setback — and hybrid (BM25 + dense, fused with reciprocal rank fusion) is frequently the
production answer.

**4. Hebrew must be measured, not assumed.** Exactly the Q1.1b concern one layer down:
morphological richness makes tokenization lossy, and code-switched notes put Hebrew prose
around English drug names. Two levers if measurement disappoints: **domain-adaptive contrastive
fine-tuning** of the retriever on de-identified local pairs — far cheaper than fine-tuning a
generative model and usually the highest-leverage single move — and falling back to the sparse
channel, which is morphology-agnostic where dense retrieval fails.

### How to decide empirically

Public leaderboards are evidence for *shortlisting* and nothing more; MTEB has no Hebrew
clinical split, and our corpus is not its corpus.

**Build a labeled retrieval set from our own notes.** Three sources, cheapest first:
- **Mined weak pairs.** Use a note's own `IMPRESSION` section as the query and the note body as
  the positive. Free, large, and noisy — good for a first ranking, not for a final decision.
  Coverage is partial: only 40 of the 90 notes carry that header at all.
- **Known-item search.** Show a clinician a note and ask what they would type to find it again.
  This yields realistic queries and unambiguous ground truth.
- **Clinician relevance judgments** over pooled top-k from all candidate systems, graded 0–3.
  Expensive, so reserved for the final two or three models. Pooling matters: judging only one
  system's results biases the evaluation toward it.

**Metrics, in priority order.**
- **Recall@k is the metric that matters for RAG.** If the evidence is not in the retrieved set,
  no amount of downstream reasoning recovers it — retrieval failure is unrecoverable, whereas
  imperfect ranking within a good candidate set is survivable.
- precision@k (or nDCG@k) and MRR for ranking quality.
- **End-to-end task metrics.** The only commercially meaningful question is whether retrieval
  improves the *extraction* F1 from Part 3. A retriever that wins on nDCG but does not move
  extraction quality has not earned deployment. See E.3 for why it can actively hurt.

**Stratify, and report per stratum.** By language (Hebrew-only / English-only / code-switched),
by note type, and by query type (concept lookup / temporal / numeric). An aggregate number will
hide Hebrew failing — which is the specific risk this corpus carries.

**Measure the operational envelope too**, because it decides feasibility:
embedding throughput (notes/sec/GPU), full-corpus index build time, query latency p50/p95,
memory per million vectors, and **the cost of re-embedding everything when the model changes**.
At millions of notes that last one is a multi-day GPU job, so model choice is close to
irreversible and deserves the up-front rigor.

**Compare properly.** Paired comparisons on identical queries, bootstrap confidence intervals,
and no declaring a winner on a one-point nDCG gap — the same small-sample caution that Part 3.2
demonstrated on its own metrics. And evaluate each model with the chunking strategy it will
actually run with, since chunk size and model interact strongly.

---

## E.2 — Which vector store, and what drives the choice?

### Hard constraints first

Being inside a secure hospital network eliminates most of the market before performance is even
discussed: **no managed service, no external network egress**, so any cloud-only offering is out. What remains must also provide auditable PHI access (who queried
which patient's data), encryption at rest, role-based access control, backup and restore, and
**working deletes** — patient erasure is a legal requirement, and several vector engines treat
deletion as an afterthought.

### Recommendation: pgvector on PostgreSQL

Not because it wins on raw vector benchmarks — it does not — but because of where the
**metadata authority** already lives.

The clinical metadata this system must filter on (`patient_id`, `visit_date`, `department`) is
already in PostgreSQL: that is literally the Part 3.1 schema. Putting the vectors beside it
means:

- **Filtering is a join against authoritative tables**, not a lookup in a denormalized copy of
  metadata inside a separate index. A copy is a thing that drifts, and drifted metadata in a
  vector store is a PHI-leak vector — a patient deleted from the EHR whose vectors still answer
  queries.
- **Transactions.** A note, its metadata and its embedding commit or fail together. Two systems
  cannot give this, so they need reconciliation jobs that are themselves a source of bugs.
- **Row-level security** can enforce that a clinician retrieves only notes for patients they are
  authorised to see. This is a first-class PostgreSQL feature and extremely difficult to
  retrofit onto a bolt-on vector database. In a hospital this argument alone can decide it.
- **The existing operational envelope** — backup, DR, audit logging, monitoring, and the
  security review that has already been done on this component — is reused rather than
  duplicated. In a locked-down environment, *every additional component is a review cycle*,
  which is a real cost that benchmark tables never show.

Capacity is adequate: pgvector's HNSW handles tens of millions of vectors, and
`pgvectorscale`'s StreamingDiskANN extends that further when the working set exceeds memory.
Millions of notes, unchunked because BGE-M3's context allows it, sits inside that envelope.

**Where it would lose**, stated plainly: at very high concurrent QPS, at billion-vector scale,
or where index build time is critical, a dedicated engine wins. So the decision is
benchmark-gated rather than dogmatic.

### The alternatives, and their real cost

Both serious contenders introduce the same cost: a second stateful system to secure, audit, back
up and keep in sync with the EHR — and that sync is exactly the drift risk described above. That
belongs in the decision, not in a footnote.

**OpenSearch is the strongest challenger, on the strength of E.1's own conclusion.** If hybrid
retrieval is the production answer — and E.1 argues it usually is, because clinical text turns on
rare tokens — then a system doing BM25, dense kNN and rank fusion in a single query is a better
fit than a vector store with BM25 bolted alongside. Filtering is its native idiom rather than a
feature. And many hospitals already run it for logs or SIEM, which means the security review,
backup and RBAC may already exist — the same argument made above *for* pgvector.

**Prefer OpenSearch over Elasticsearch, and the reason is the licence.** Elasticsearch left
OSI-approved licensing in 2021, and the features that matter most for PHI — document-level and
field-level security — sit in paid tiers. OpenSearch is Apache 2.0 with fine-grained access
control included. This is Q1.1a's point arriving again: on-prem, licence terms are load-bearing,
not a footnote. Against it: JVM operational weight, and vector search that is newer than its
lexical core.

**Qdrant** is the choice if the requirement is pure vector latency rather than hybrid:
self-hostable, small footprint, and it performs **filter-aware HNSW traversal** rather than
filtering after search. If benchmarking shows pgvector cannot meet latency targets, this is the
move.

**The hybrid argument does not actually settle it, though.** PostgreSQL can do lexical retrieval
too — natively via `tsvector`/GIN, or with real BM25 scoring through the `pg_search` extension —
so pgvector plus full-text search gives hybrid in one system *while keeping the metadata
authority and row-level security that made it the recommendation*. That is the combination I
would benchmark first, and it is why OpenSearch is the challenger rather than the answer.

Briefly on the rest: **Milvus** scales furthest but its component sprawl (etcd, object store,
multiple services) is a liability where each component needs security review. **FAISS** is a
library, not a store: no persistence, no auth, and no filtering at all (see below). Fine as an
embedded index behind your own service, wrong as the system of record.

### Metadata filtering

The filter has to be applied **before or during** the vector search, never after. Worth stating
only because it is not always a choice: FAISS's API takes a vector and returns global top-k, so
anything built directly on it post-filters by construction — and the failure is an empty result
rather than an error. For *"patient 12345, last six months"* — perhaps 40 notes among 10 million
— the globally nearest 100 contain none of them, so a RAG pipeline answers with no context at
all while the retrieval layer reports success.

Three mechanisms, in the order I would apply them:

**1. Filter first, then search exactly — for patient-scoped queries.** The dominant clinical
access pattern is "this patient's records", and after filtering to one patient the candidate set
is tens or hundreds of vectors. Brute-force cosine over 40 vectors is sub-millisecond and
*exactly* correct, with no ANN recall loss. The important consequence: **most clinical retrieval
barely needs an ANN index at all**, which is another reason the dedicated-engine performance
argument is weaker here than it first appears.

```sql
SELECT n.note_id, n.note_text
FROM notes AS n
JOIN visits AS v ON v.visit_id = n.visit_id
WHERE v.patient_id = %(patient_id)s
  AND n.created_at >= %(since)s
ORDER BY n.embedding <=> %(query_vec)s
LIMIT 10;
```

With an index on `visits.patient_id` the planner filters first and sorts a small set — no ANN
index involved, and no recall cliff.

**2. Filter-aware ANN traversal — for corpus-wide queries.** Where the filter is broad
(a department, a year) and the candidate set is still large, the index itself must respect the
filter during graph traversal. Qdrant does this natively; in pgvector the equivalent is partial
HNSW indexes over the common filter values.

**3. Partition on the highest-cardinality filter.** Partitioning by department or by time range
turns a filter into partition pruning, so the scan never touches irrelevant data.

**Store the E.1 concept CUIs as metadata too.** Normalized concepts turn a fuzzy semantic
question into an exact filter — "notes mentioning C0027051 (myocardial infarction)" — which is
both faster and more auditable than hoping cosine similarity captures it.

---

## E.3 — A concrete failure mode where RAG makes clinical extraction worse

### Cross-patient contamination turns a safe abstention into a confident error

A RAG layer retrieves the *k* most similar notes and adds them to the Part 2 prompt. Patient A's
note is terse and never states a response status — the majority case, since **69% of
`Oncology.csv` contains no disease-status vocabulary at all**. Its nearest neighbors are
therefore other patients' oncology notes of the same cancer type, skewed toward the semantically
richest ones, which are exactly those with explicit progression language:

> "Restaging CT demonstrates new hepatic lesions … consistent with progressive disease."

The model returns `PD`, confidence 0.9, with a **verbatim supporting quote** — that sentence
really is in its context. Without retrieval the note would have taken the D13 path: `Non-PD`,
confidence ≤ 0.2, empty evidence, a machine-detectable abstention routed to a clinician. RAG
replaced a safe, reviewed outcome with a confident, evidence-backed, wrong, *unreviewed* one —
the confidence suppressing the review that would have caught it.

The grounding check in [`src/validation.py`](../src/validation.py) catches this only because it
verifies quotes against **the note under classification**, not against "the provided context" —
the natural phrasing once RAG exists, and one that would let the record pass. **The distinction
between the source document and the context window is load-bearing**, and a RAG retrofit is
precisely when it gets blurred.

### Why it generalizes: retrieval cannot say "nothing here"

**ANN search always returns *k* results.** There is no null answer and no calibrated distance
that means "nothing relevant", so *nearest* and *relevant* collapse into one thing. Hence the
unmatched-term case: where the **corpus** lacks a concept, retrieval returns the
least-irrelevant notes; where the **embedding model** lacks it — a rare biomarker, a local
abbreviation, Hebrew — the query vector is near-arbitrary and the neighbors effectively random.
Both look identical to success. Note the asymmetry with E.2's post-filter: an empty result set is
visible, *k* plausible near-misses are not.

Three further variants share the root. Retrieval surfaces **the same patient's older note** and
re-opens the temporality trap (D9) after the prompt had closed it. **Dilution** buries the one
decisive sentence among *k*=10 notes, so accuracy can fall below the no-retrieval baseline while
every retrieval metric looks healthy. **Negation inversion** follows from embeddings' weakness on
negation: *"no evidence of progression"* and *"evidence of progression"* are near neighbors.

### Mitigations, and the principle

Scope retrieval to the same patient as a hard filter (E.2), not a prompt instruction. Keep
retrieved text in a `<reference>` block that may never be quoted as evidence. Ground evidence by
**character offset** into the target note, which makes a foreign quote inexpressible rather than
merely detectable. Stamp `patient_id` and date on every chunk and assert them after retrieval.
Add a **relevance floor** so the retriever can return nothing and the pipeline can abstain into
D13. Use the hybrid **sparse** channel (E.1) for rare literal strings and negation.

**RAG is appropriate for reference knowledge and dangerous for patient facts.** Fetching the
RECIST 1.1 criteria or a drug classification adds what the note cannot supply and carries no
contamination risk. Fetching other patients' notes — or the same patient's from other times —
injects facts the model cannot reliably keep separate from the document it is meant to be
reading. For extraction from a specific document the document is ground truth and everything else
is a contamination risk, so RAG must earn its place per task, measured end to end. Here the
default answer is no.
