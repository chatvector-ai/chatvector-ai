# Gemini quality baseline

This file is an engineering baseline for the ChatVector-AI reference
configuration that was actually run. It is not a public benchmark and it is
not a provider certification matrix.

The numbers below come from one clean-tenant run of the checked-in Brinewick
corpus through `load-eval-corpus`, `eval --answers`, and `eval-conversations`.
They are not copied from Audit 2.

## Configuration

This Gemini configuration is the quality reference: Gemini 2.5 Flash, Gemini
embeddings, and default retrieval. The process `LLM_MODEL` and
`EMBEDDING_MODEL` values were unset, so the provider defaults ran. The
generation model printed here is the string `generate_answer` returned.

| Field | Value that ran |
|---|---|
| LLM provider | `gemini` |
| Generation model | `gemini-2.5-flash` |
| Embedding provider | `gemini` |
| Embedding model | `models/gemini-embedding-001` |
| Persona (`PROMPT_PERSONA`) | `default` |
| Chunk strategy | `fixed` |
| Chunk size | `1000` |
| Chunk overlap | `200` |
| Retrieval hybrid | off |
| Retrieval reranking | off |
| Eval `match_count` | `10` |
| Conversation `match_count` | `5` (in-process chat default) |
| Query transformation | off |
| Embedding cache | off |
| Corpus | `brinewick-transit-cooperative` |
| Corpus version (question-file SHA-256) | `bd79fa95e097c2df5acef9da38380b8adc36955bebe49ec0833bc8ae43f02a64` |
| Eval run id | `381d48b9-7b23-4952-8796-711210aaa02b` |
| Eval timestamp | `2026-11-07T17:23:09.132581+00:00` |
| Eval tenant | `eval-tenant` |

`backend/.env` still lists `PROMPT_PERSONA=conversational`. The API process
had `PROMPT_PERSONA=default` from Compose, and `load_dotenv` does not override
that. The persona that was active is `default`.

## Retrieval

Rank metrics are published with the packed-context presence fraction. A chunk
can be retrieved or globally selected and still absent from the generation
context; packed-context presence is the fraction of labeled evidence chunks
that the packer included.

Aggregate over the 29 labeled-relevance rows (2 no-evidence / refusal rows
omit rank metrics and packed-context presence):

| Metric | Score |
|---|---|
| MRR | 1.0000 |
| recall@5 | 1.0000 |
| nDCG@5 | 1.0000 |
| recall@10 | 1.0000 |
| nDCG@10 | 1.0000 |
| packed-context presence fraction | 1.0000 |

Multi-document ranking used the same arm. `q-leave-synthesis` (parental leave
plus current PTO) and `q-dinner-conflict` (expense vs travel dinner limits)
each retrieved, globally selected, and packed both labeled chunks
(packed-context presence 1.0000, recall@5 1.0000, nDCG@5 1.0000).

## Answers

Answer labels were scored by the eval answer arm with `generate_answer`.
Completeness, citation support, and groundedness are means over the rows that
carry those labels. Refusal correctness is the mean of the two refusal rows.

| Metric | Score | Rows |
|---|---|---|
| Completeness | 0.9138 | 29 |
| Groundedness | 1.0000 | 31 |
| Citation support | 1.0000 | 29 |
| Refusal correctness | 1.0000 | 2 |

Both refusal rows (`q-absent-sabbatical`, `q-refusal-address`) answered
"Not enough information." Completeness dropped below 1.0000 on three rows:
`q-stale-pto-document` (0.0; named the file instead of "15 paid days off"),
`q-leave-synthesis` (0.5; packed both documents and stated "18 annual paid
days off", which does not contain the labeled substring "18 paid days off"),
and `q-release` (0.0; answered "Saltmere yard cutover" instead of "gangway
sensors").

## Conversation

The scripted harness played 11 fixed scenarios against the same tenant.
Follow-up success is 7 of 11 scenarios passed.

Passed scenario classes: `absent_answer`, `correction`, `demonstrative`,
`ordinal`, `pronoun`, `return_to_earlier_subject`, `topic_switch`.

Failed scenario classes:

| Class | Scenario | Failure |
|---|---|---|
| `ambiguity` | `ambiguity-pass-fare` | Turn 0 expected a refusal ("Not enough information") and forbade fare codes; the answer quoted HP-100, HPP-200, and LP-330. |
| `contradictory_sources` | `contradictory-dinner-limits` | Turn 1 applied history resolution but `history_resolved_query` was empty, so the "travel orders" resolution label failed. |
| `long_session` | `long-session-brinewick` | Turn 5 omitted labeled fact `HPP-200`. |
| `multi_document_continuation` | `multi-document-leave` | Turn 1 applied history resolution with an empty resolved query, and the answer used "18 annual paid days off" rather than the labeled "18 paid days off". |

The harness exits non-zero when any script fails. Those failures are part of
this record. Retrieval defaults, persona files, and the generator were not
changed to raise the scores.

## Latency

Retrieval stage timings are copied from the eval export (`timing_ms` on each
query). Answer latency is the `latency_ms` `generate_answer` returned
(`answer_latency_ms`). All 31 queries recorded both.

Retrieval stage timings, milliseconds:

| Stage | n | Mean | Median | Min | Max |
|---|---|---|---|---|---|
| transform | 31 | 0.0 | 0.0 | 0 | 0 |
| embed | 31 | 193.2 | 193.0 | 152 | 237 |
| search | 31 | 148.6 | 164.0 | 12 | 290 |
| rerank | 31 | 0.0 | 0.0 | 0 | 0 |
| context | 31 | 0.0 | 0.0 | 0 | 0 |
| total | 31 | 342.5 | 362.0 | 187 | 494 |

Answer latency from `generate_answer`, milliseconds:

| | n | Mean | Median | Min | Max |
|---|---|---|---|---|---|
| `answer_latency_ms` | 31 | 1317.2 | 1247.0 | 572 | 2665 |

Transform and rerank are zero because query transformation and reranking were
off.

## Integration support is not quality validation

A provider can be integration-tested by initializing, embedding, generating,
streaming, timing out, and returning valid output. That does not make it
quality-benchmarked. Gemini, on this configuration — Gemini 2.5 Flash, Gemini
embeddings (`models/gemini-embedding-001`), persona `default`, and default
retrieval — is the quality reference from the audits. No table certifies other
providers. This report does not include a certification matrix and does not
record a local or Ollama quality run.

## Erratum

The configuration block records the question file that this run scored.
Its SHA-256 is `bd79fa95e097c2df5acef9da38380b8adc36955bebe49ec0833bc8ae43f02a64`.
The tables above were not recomputed. Completeness 0.9138, including the
narratives for `q-release` and `q-stale-pto-document`, was computed from those
previous labels.

Three ground-truth labels were corrected after the run:

- `q-release` expected "gangway sensors". The corpus says REL-ENG-77 marks the Saltmere yard cutover, so the expected fact is now "Saltmere yard cutover".
- `q-stale-pto-document` expected "15 paid days off". The question asks which document is the 2022 copy, so the expected fact is now the document title "Captain paid time off (2022)".
- `q-chunk-boundary` cited chunk 3. Under the declared fixed/1000/200 chunker the phrase "north lantern steady" is in chunk 4, so the citation target is now chunk 4. Relevant chunks 3 and 4 are unchanged.

The corrected question file SHA-256 is `55e532fcff665d4f641ab18ff3d527a36e2619958b145ceb164be759c8d73bcd`.

The recorded `contradictory_sources` failure matches a harness check that treated an applied resolution echo, which omits `history_resolved_query`, as a miss. That scenario was not re-run and stays in the failed table above. The `multi_document_continuation` fact miss is unchanged.
