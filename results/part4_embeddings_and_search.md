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

| Model | Type | Strengths | Weaknesses | Role |
| --- | --- | --- | --- | --- |
| **BGE-M3** | General, multilingual | Broad multilingual coverage including Hebrew; 8,192-token context, so whole notes fit unchunked; emits **dense + sparse + multi-vector** from one model, giving lexical and semantic retrieval without a second system | General-domain: no clinical supervision; larger and slower than single-signal encoders | **Primary retriever** |
| **multilingual-E5** (large / instruct) | General, multilingual | Strong, well-established multilingual baseline; cheap to serve | Requires `query:` / `passage:` prefixes — omit them and quality degrades sharply, a real operational footgun; 512-token limit on base variants forces chunking | Baseline to beat |
| **GTE-multilingual** | General, multilingual | 8,192 context, notably smaller and faster than BGE-M3 | Fewer retrieval signals; less battle-tested clinically | Throughput candidate |
| **MedCPT** | Domain, English | Trained on ~255M PubMed query–article click pairs, so it is a genuine *retriever* rather than a repurposed encoder; strong biomedical relevance | Trained on **PubMed abstracts, not clinical notes** — academic prose differs sharply from telegraphic EHR text full of abbreviations; English only | Literature / guideline corpus only |
| **SapBERT** | Domain, English | Self-aligned over UMLS synonyms; excellent at mapping surface forms to concepts (`MI` ↔ `myocardial infarction`) | An **entity linker, not a passage retriever** — tuned for short strings, not documents; English only | Concept normalization layer |
| **BM25** | Lexical | No training, no GPU, no drift; unbeatable on exact drug names, ICD codes, identifiers | No semantics; misses paraphrase | **Mandatory baseline** |

### The architecture this implies

**1. BGE-M3 as the primary retriever.** Multilingual coverage is non-negotiable given the
Hebrew/English mix, and its 8,192-token context comfortably holds whole notes — no note in
`Oncology.csv` exceeds ~2,000 tokens, so chunking can be avoided entirely, which removes a whole
class of boundary bugs. Its **sparse signal is the reason to prefer it
over a dense-only model**: clinical text turns on rare tokens (drug names, ICD codes, `s/p`,
`PR`) that dense embeddings smooth away, and getting lexical matching from the same model
avoids running and tuning a second retrieval system.

**2. SapBERT used for what it is actually good at.** Not as the passage retriever, but as a
concept-normalization layer: canonicalize entity mentions to UMLS CUIs so `MI`,
`myocardial infarction` and the Hebrew equivalent collapse to one concept. Those CUIs then
become *metadata* (see E.2) and feed the sparse channel. Using SapBERT to embed whole notes
would be a category error — it is trained on short synonym pairs.

**3. MedCPT only if there is a literature corpus.** It is the right tool for
query→publication retrieval and the wrong tool for EHR notes. Pointing it at clinical text
because it says "Med" in the name is the mistake to avoid.

**4. BM25 as the floor, run first.** On clinical corpora a lexical baseline is often
embarrassingly competitive, because much clinical retrieval is known-item search for a named
drug or code. If a neural retriever cannot beat BM25 on our own queries, that is a finding, not
a setback — and hybrid (BM25 + dense, fused with reciprocal rank fusion) is frequently the
production answer.

**5. Hebrew must be measured, not assumed.** Exactly the Q1.1b concern one layer down:
morphological richness makes tokenisation lossy, and code-switched notes put Hebrew prose
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

Same discipline as Q1.2b applies — two annotators, Cohen's κ on the judgments, adjudication by
a third, and model scores read against the human agreement ceiling.

**Metrics, in priority order.**
- **Recall@k is the metric that matters for RAG.** If the evidence is not in the retrieved set,
  no amount of downstream reasoning recovers it — retrieval failure is unrecoverable, whereas
  imperfect ranking within a good candidate set is survivable.
- nDCG@10 and MRR for ranking quality.
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
discussed: **no managed service, no external network egress**, so Pinecone and any
cloud-only offering are out. What remains must also provide auditable PHI access (who queried
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

### The alternative, and its real cost

**Qdrant** is the strongest dedicated option here: self-hostable, small footprint, and — most
relevantly — it performs **filter-aware HNSW traversal** rather than filtering after search,
with payload indexes on metadata fields. If benchmarking shows pgvector cannot meet latency
targets, this is the move.

But it introduces a second stateful system to secure, audit, back up and keep in sync with the
EHR, and that sync is exactly the drift risk described above. That cost belongs in the decision,
not in a footnote.

Briefly on the others: **Milvus** scales furthest but its component sprawl (etcd, object store,
multiple services) is a genuine liability where each component needs security review.
**Elasticsearch / OpenSearch** deserves consideration because it gives BM25 and dense vectors in
one system — attractive given E.1's hybrid conclusion — and many hospitals already operate it.
**FAISS** is a library, not a store: no metadata filtering, no persistence, no auth. Fine as an
embedded index behind your own service, wrong as the system of record.

### Metadata filtering is the crux, and post-filtering is the trap

The naive implementation retrieves top-k by vector similarity and *then* discards rows failing
the filter. This breaks silently and badly under selective filters.

Concretely: *"notes for patient 12345 in the last six months."* That patient has perhaps 40
notes among 10 million. An ANN search returns the 100 globally nearest vectors; the probability
any belong to patient 12345 is negligible. **Post-filtering therefore returns an empty set** —
and in a RAG pipeline an empty context is worse than a wrong one, because the model answers
with no grounding at all and confabulates. The retrieval layer reports success; the failure
surfaces as a hallucination downstream, far from its cause.

Three correct approaches, in the order I would apply them:

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

### The failure: cross-patient contamination converts a safe abstention into a confident error

**Setup.** The Part 2 pipeline classifies a note as PD or Non-PD. To help on hard cases, a RAG
layer retrieves the *k* most semantically similar notes from the corpus and adds them to the
prompt as context.

**The case.** Patient A's note is terse — a brief oncology follow-up that never states a
response status. This is not a corner case: **69% of `Oncology.csv` contains no disease-status
vocabulary at all**, so it is the majority of the corpus.

**What retrieval does.** Because the note is short and unspecific, the nearest neighbours are
other oncology notes with the same cancer type and treatment line — and the notes that are
*semantically richest*, hence closest, are disproportionately the ones with explicit progression
language. So the retrieved context now contains, from **other patients**:

> "Restaging CT demonstrates new hepatic lesions and enlargement of the retroperitoneal nodes,
> consistent with progressive disease."

**The output.** The model returns `PD` with a confidence of 0.9 — and, worst of all, a
**verbatim supporting quote**, because that sentence genuinely exists in its context. Every
surface signal of a well-grounded answer is present. The answer is about a different patient.

**Why this is worse than not using RAG at all.** Without retrieval this note would have hit the
D13 path: `Non-PD`, confidence ≤ 0.2, empty evidence — a machine-detectable abstention routed to
a clinician. RAG replaced a *correct, safe, reviewed* outcome with a *confident, evidence-backed,
wrong, and unreviewed* one. That is the precise inversion that makes this failure dangerous:
confidence suppresses the very review that would have caught it. A pipeline can lose safety by
adding capability.

**Why our design happens to catch it — and how easily it would not.** The grounding check in
[`src/validation.py`](../src/validation.py) verifies every quote against **the note under
classification**, not against "the provided context". The contaminating quote is absent from
patient A's note, so `find_ungrounded_quotes` flags it and the record fails with
`evidence_not_in_source`. This is luck turned into design: had the check been written against
"the context" — the natural phrasing once RAG exists — it would pass. **The distinction between
*the source document* and *the context window* is load-bearing**, and a RAG retrofit is exactly
when it gets blurred.

**Mitigations, in order of strength:**

1. **Scope retrieval to the same patient.** For extraction *from a document*, cross-patient
   retrieval has almost no upside and unbounded downside. Enforced as a hard filter (E.2), not a
   prompt instruction.
2. **Separate the channels.** Retrieved text goes in a `<reference>` block explicitly marked as
   *not* the subject of classification, and the target note in `<clinical_summary>`. Evidence may
   only be quoted from the latter.
3. **Ground by offset, not by string.** Require evidence as character offsets into the target
   note. A quote from elsewhere then cannot be expressed at all — the failure becomes impossible
   rather than detectable.
4. **Stamp provenance on every chunk** (`patient_id`, note date) and assert it after retrieval.

### Three shorter variants worth naming

**Temporal contamination within one patient.** Retrieval is semantic, not chronological. Ask
about current status and retrieval happily surfaces the *same patient's* 2023 note saying
"progressive disease". This re-introduces the temporality trap (D9) through the retrieval layer
*after* the prompt had solved it — a defense at one layer silently undone by a new layer.
Mitigation: date-filter to the clinically relevant window and stamp every retrieved chunk with
its date.

**Dilution of the real evidence.** Padding the context with k=10 similar notes pushes the target
note's one decisive sentence into the middle of a long context, where attention is weakest.
Extraction accuracy can fall *below* the no-retrieval baseline while every retrieval metric
looks healthy — which is exactly why E.1 insists on end-to-end task metrics rather than nDCG
alone.

**Negation-driven retrieval inversion.** Embeddings are notoriously weak on negation: *"no
evidence of progression"* and *"evidence of progression"* are near neighbours. Retrieval meant to
find supporting evidence returns the semantic opposite. Mitigation: the hybrid sparse channel
from E.1, and never letting retrieval participate in the decision itself.

### The principle

**RAG is appropriate for retrieving reference knowledge and dangerous for retrieving patient
facts.** Fetching the RECIST 1.1 criteria, a departmental protocol, or a drug's classification
adds context the note cannot supply and carries no contamination risk. Fetching other patients'
notes — or the same patient's notes from other times — injects facts that the model cannot
reliably keep separate from the document it is supposed to be reading.

For extraction from a specific document, **the document is the ground truth and everything else
is a contamination risk**. RAG must therefore earn its place per task, measured end to end, and
its default answer for this particular task is no.
