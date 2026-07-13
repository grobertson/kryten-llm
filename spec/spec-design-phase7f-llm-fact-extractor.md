---
title: Phase 7f - LLM-Driven Fact Extractor (Independent Provider, Scored Extraction)
version: 0.1 (draft)
date_created: 2026-07-13
last_updated: 2026-07-13
owner: kryten-llm development team
tags: [design, phase7, phase7f, memory, fact-extraction, llm, scoring, embeddings]
---

# Introduction

This specification defines Phase 7f of kryten-llm: an **LLM-driven `FactExtractor`** that
replaces (or layers over) the heuristic extractor from the parent Phase 7 design
([spec-design-phase7-pluggable-context-memory.md](spec-design-phase7-pluggable-context-memory.md)).

Where the heuristic extractor uses regexes and keyword scoring, the LLM extractor sends a
short window of chat to a **dedicated, independently-configured LLM** and asks it to produce
paraphrased, attributed, *scored* candidate facts as strict JSON. The subsystem adds three
scoring signals — **attribution confidence**, **sentiment**, and **novelty** (the
"cardinality/similarity" signal) — plus a persistent **importance** counter that turns
repeated mentions of the same fact into a durable salience signal about a user's personality.

This document conforms to the interfaces and constraints already fixed by Phase 7 (the
`FactExtractor` Protocol, the `LongTermMemoryProvider`, the `Embedder`/`VectorStore`
abstractions, the safety gate, and the opt-in `memory.long_term` config subtree). It only
specifies the extractor and the additional scoring/persistence behaviour needed to support it.

## 1. Purpose & Scope

### Purpose
Give kryten-llm a **high-signal, low-noise** long-term memory writer by:
1. Extracting facts with an LLM rather than regex heuristics, improving paraphrase quality,
   category accuracy, and — critically — **who a fact is actually about** in a noisy multi-user chat.
2. Running that LLM on a **completely separate API connection** from message generation, so
   memory extraction can use a cheaper/local/slower model and never contends with, depends on,
   or leaks the response model's credentials or endpoint.
3. Producing a **structured, tunable score set** per candidate fact (`confidence`, `sentiment`,
   `novelty`) and maintaining a persistent `importance` counter.
4. Using `novelty` + `importance` to **deduplicate** writes *and* to rank retrieval, so facts a
   user repeats become both non-duplicated and more prominent in future prompts.

### Scope
- A `LLMFactExtractor` implementing the existing `FactExtractor` Protocol (Phase 7 §3.4/§4.2).
- A **dedicated extractor LLM connection** (its own `LLMManager` instance + provider config
  subtree), fully isolated from `llm_providers` / `default_provider`.
- A strict **JSON output contract** (schema + validation + repair fallback).
- A **scoring & persistence model**: mechanical `novelty` (embedding-based), the `importance`
  counter, confidence gating, and sentiment metadata.
- An optional **heuristic pre-gate** layered in front of the LLM to control cost.
- **Extraction cadence** (per-user batching off the response critical path).
- Configuration schema additions under `memory.long_term.extractor`.
- Requirements, interfaces, phased rollout, testing, and risks.

### Out of Scope (this sub-phase)
- A separate reranker/scoring *model* (see REQ-042 / Open Questions — single extraction call +
  embedder is the MVP).
- Cross-user identity/alias resolution (still username-keyed, per parent Phase 7).
- Conversation summarisation / episodic compression.
- Changes to the `Embedder`, `VectorStore`, safety gate, or seeding CLI beyond additive
  metadata fields.

### Assumptions
- Phases 7a–7e are complete: the `ContextPipeline`, `LongTermMemoryProvider`, `Embedder`
  (ONNX default), `VectorStore` (Chroma default), and `safety.py` gate exist and work.
- The existing `LLMProvider` Pydantic model and the OpenAI-compatible calling code in
  `LLMManager` are reusable for the extractor connection.
- The service has a writable data directory and can run background tasks off the response path.

### Intended Audience
Developers implementing 7f, architects reviewing the isolation/scoring model, QA writing test plans.

## 2. Definitions

| Term | Definition |
|------|------------|
| **Extractor LLM** | The independently-configured model that reads chat and emits scored facts. Distinct from the message-generation model. |
| **Extracted Fact** | The *pure* output of the extractor for one candidate: target user, category, summary, confidence, sentiment, evidence. No datastore state. |
| **Attribution Confidence** (`confidence`) | 0–1 certainty that the fact is about `target_user`, judged holistically over a look-back window. |
| **Sentiment** (`sentiment`) | 0–1 affect of the fact/statement. 1 = very positive, 0 = very negative, 0.5 = neutral. |
| **Novelty** (`novelty`) | 0–1 signal computed mechanically as `1 − max_cosine_similarity` to the user's existing facts. **1 = nothing similar stored; 0 = exact duplicate.** This is the "cardinality/similarity" score from the request. |
| **Importance** (`importance`) | A persistent per-fact counter incremented each time a new, low-novelty mention matches the stored fact. A salience signal, not just a dedup byproduct. |
| **Heuristic Pre-Gate** | The Phase 7 heuristic candidate/safety filter, run cheaply before the LLM to drop obvious non-facts. |
| **Extraction Batch** | A small per-user window of qualifying messages accumulated then sent to the extractor LLM in one call. |
| **Structured Output** | LLM response constrained to a JSON schema (native `response_format` when supported; prompt-instructed + repair otherwise). |

## 3. Requirements, Constraints & Guidelines

### 3.1 Independent Extractor Connection (isolation)

- **REQ-001**: The extractor MUST use a **dedicated LLM connection** configured under
  `memory.long_term.extractor.llm`, instantiated as its **own `LLMManager`** with its own
  provider map and priority list.
- **REQ-002**: The extractor connection MUST NOT read, import, fall back to, or otherwise depend
  on `llm_providers`, `default_provider`, `default_provider_priority`, or the response-generation
  `LLMManager` instance. There MUST be no code path where a missing extractor config silently
  borrows the message-generation credentials or endpoint.
- **REQ-003**: The extractor connection MUST reuse the existing `LLMProvider` model and
  `${ENV_VAR}` API-key resolution, so its `base_url`, `api_key`, `model`, `temperature`,
  `timeout_seconds`, `max_retries`, and `custom_headers` are configured identically to (but
  separately from) message-generation providers.
- **REQ-004**: The extractor MAY be configured with multiple providers and a priority order
  (reusing `LLMManager` fallback). The shipped example config uses a single local provider.
- **SEC-001**: Extractor API keys MUST never be logged; reuse the existing redaction behaviour
  in `LLMManager._call_openai_provider`.

### 3.2 LLM Extraction & the JSON Contract

- **REQ-010**: The `LLMFactExtractor` MUST implement the Phase 7 `FactExtractor` Protocol
  (`extract(messages, user) -> list[Fact]`) and remain **side-effect free** (REQ-033 of the
  parent): it performs no datastore reads/writes and computes no `novelty`/`importance`.
- **REQ-011**: For each batch the extractor MUST send the extractor LLM a prompt containing:
  the ordered look-back window (each message tagged with author + index), the identity of the
  "focus" user(s) being extracted for, and the JSON output instructions.
- **REQ-012**: The extractor MUST request a strict JSON object of the form:

  ```json
  {
    "facts": [
      {
        "target_user": "User42",
        "category": "preference",
        "summary": "Loves the film Aliens (1986)",
        "confidence": 0.86,
        "sentiment": 0.92,
        "evidence_message_index": 5
      }
    ]
  }
  ```

  - `target_user` (string): who the fact is about.
  - `category` (enum): `preference|habit|past|life_context|self_description|misc`.
  - `summary` (string): short paraphrased fact (see GUD-002 length budget).
  - `confidence` (number 0–1): attribution confidence (§3.4).
  - `sentiment` (number 0–1): affect (§3.4).
  - `evidence_message_index` (int): index into the supplied window for auditability.
- **REQ-013**: The extractor MUST validate the response against the schema. On invalid/partial
  JSON it MUST attempt a **single bounded repair** (re-parse, then one corrective re-prompt) and,
  if still invalid, drop the batch and log — never raise into the caller (fail-open, consistent
  with the pipeline's fail-open contract).
- **REQ-014**: Structured-output mode MUST be configurable (`auto|json_schema|prompt`):
  - `json_schema`: use the provider's native `response_format` json-schema constraint.
  - `prompt`: instruct JSON in the prompt and parse/repair.
  - `auto` (default): try `json_schema`; on unsupported-parameter errors from the endpoint, fall
    back to `prompt` for the remainder of the process and log the downgrade once.
- **REQ-015**: The extractor MUST cap facts per batch (`cadence.max_facts_per_batch`) and MUST
  drop any fact whose `target_user`, `category`, or `summary` is missing/empty.

### 3.3 Heuristic Pre-Gate & Extraction Cadence (cost control)

- **REQ-020**: When `extractor.heuristic_pregate` is true (default), each inbound message MUST
  pass the Phase 7 safety gate **and** the heuristic candidate filter before it is eligible to
  enter an extraction batch. Messages failing the gate never reach the LLM.
- **REQ-021**: The extractor MUST accumulate qualifying messages into a **per-user batch** and
  flush the batch when either `cadence.batch_max_size` messages are buffered **or**
  `cadence.batch_idle_seconds` elapse since the user's last qualifying message.
- **REQ-022**: All extractor LLM calls MUST run **off the response critical path** (background
  task), consistent with the parent's fire-and-forget write path (REQ-011/GUD-001). A slow or
  failing extractor MUST NOT delay or block response generation or retrieval.
- **REQ-023**: The look-back window sent to the LLM (`attribution.lookback_messages`) MAY be
  larger than the batch itself (the batch is *what to extract*; the look-back is *context for
  attribution*), drawn from the same rolling buffer the pipeline already maintains.

### 3.4 Scoring: Confidence, Sentiment, Novelty, Importance

- **REQ-030**: **Confidence gating.** Facts with `confidence < attribution.min_confidence`
  (default `0.6`) MUST be dropped before persistence. Look-back for attribution defaults to
  `attribution.lookback_messages = 8`.
- **REQ-031**: **Sentiment.** `sentiment` MUST be stored as fact metadata. For this sub-phase it
  is **metadata only** — it MUST NOT gate storage or retrieval. (Future ranking use is allowed
  behind config.)
- **REQ-032**: **Novelty is mechanical and authoritative.** `novelty` MUST be computed by the
  `LongTermMemoryProvider` as `1 − max_cosine_similarity` between the candidate summary's
  embedding and the querying user's existing fact embeddings. Any relatedness hint the LLM emits
  is advisory only and MUST NOT override the mechanical value.
- **REQ-033**: **Dedup / merge (high similarity).** If `novelty <= scoring.dedup_novelty_max`
  (default `0.08`; i.e. cosine ≥ ~0.92) the candidate is treated as the **same fact**:
  the provider MUST NOT insert a new record; instead it MUST increment `importance` on the
  matched fact, refresh `last_seen`, and keep the newest `evidence`.
- **REQ-034**: **Related-mention salience (moderate similarity).** If
  `scoring.dedup_novelty_max < novelty <= scoring.importance_increment_below`
  (default upper bound `0.15`) the candidate is a **distinct but closely related** fact:
  the provider MUST insert it as a new record **and** increment `importance` on its nearest
  existing neighbour (the user keeps circling the same topic).
- **REQ-035**: **Novel fact.** If `novelty > scoring.importance_increment_below` the candidate is
  inserted as a new record with `importance = 1`.
- **REQ-036**: `importance` MUST be persisted in fact metadata, monotonically non-decreasing per
  fact, and bounded by `scoring.importance_cap` (default `10000`) to avoid overflow/pathology.
- **REQ-037**: **Retrieval boost.** When the `LongTermMemoryProvider` ranks retrieved facts it
  MUST blend `importance` and recency into the base similarity score:

  ```
  rank = similarity_to_query
       + retrieval_boost.importance_weight * normalized_log_importance
       + retrieval_boost.recency_weight   * recency_factor
  ```

  Defaults: `importance_weight = 0.2`, `recency_weight = 0.1`. `importance` therefore acts as a
  booster/tie-breaker, never fully overriding semantic relevance.
- **REQ-038**: Every stored fact record MUST carry, in addition to the Phase 7 metadata
  (`user, category, source, created_at, evidence`): `confidence`, `sentiment`,
  `novelty_at_write`, `importance`, `last_seen`, and the `embedder_id` (per parent REQ-022).

### 3.5 Privacy, Safety & Constraints

- **CON-001**: The Phase 7 safety gate (`memory/safety.py`, CON-001 of the parent, PII-exclusion
  including the corrected drug/explicit-age exclusion) MUST run before extraction and again
  before persistence. The LLM MUST NOT be relied upon to enforce privacy.
- **CON-002**: The LLM extractor MUST be opt-in: it is only active when
  `memory.long_term.enabled` is true **and** `extractor.type == "llm"`. Default remains the
  heuristic extractor so existing deployments are unaffected.
- **CON-003**: The extractor MUST NOT be permitted to invent PII or copy raw disallowed content
  into `summary`; summaries MUST be re-checked by the safety gate, and any summary that fails is
  dropped (not stored).
- **CON-004**: The extractor connection MUST enforce its own `timeout_seconds`; a hung extractor
  endpoint MUST NOT accumulate unbounded background tasks (bound in-flight batches per user).
- **GUD-001**: Keep extractor `temperature` low (default `0.1`) for stable, parseable output.
- **GUD-002**: Keep `summary` compact (≤ ~120 chars) to preserve shared prompt budget (parent GUD-002).
- **GUD-003**: Prefer a small/cheap/local extractor model; extraction quality benefits more from a
  good prompt + look-back window than from a large model, and cost/isolation matter more here.

## 4. Architecture & Interfaces

### 4.1 Data flow (write path)

```
inbound chatmsg
      │  (heuristic pre-gate + safety gate)               REQ-020, CON-001
      ▼
 per-user Extraction Batch  ── size or idle flush ──►     REQ-021
      ▼  (background task, off critical path)             REQ-022
 LLMFactExtractor.extract(window, user)                   REQ-010..015
      │   extractor LLMManager (dedicated connection)     REQ-001..004
      ▼   -> [ExtractedFact{summary,category,confidence,sentiment,evidence}]
 confidence gate (drop < min_confidence)                  REQ-030
      ▼
 LongTermMemoryProvider (stateful):                       REQ-032..038
      ├─ Embedder.embed(summary)
      ├─ VectorStore.query(user facts)  -> novelty = 1 - max_cosine
      ├─ novelty <= dedup_novelty_max            -> merge: importance++ on match, no insert
      ├─ <= importance_increment_below           -> insert new + importance++ on neighbour
      └─ else                                     -> insert new (importance=1)
      ▼
 safety re-check on summary -> VectorStore.upsert (with confidence/sentiment/novelty/importance)
```

### 4.2 Interfaces (illustrative; extends Phase 7 §4.2)

```python
# kryten_llm/components/memory/extractor.py  (extends the Phase 7 Fact model)

@dataclass
class ExtractedFact:
    """Pure output of an extractor for one candidate fact (no datastore state)."""
    target_user: str
    category: str          # preference|habit|past|life_context|self_description|misc
    summary: str
    confidence: float      # 0..1 attribution certainty
    sentiment: float       # 0..1 (1 positive, 0 negative, 0.5 neutral)
    evidence: dict         # {index,time,message} into the supplied window

class LLMFactExtractor:                      # implements FactExtractor Protocol
    id = "llm"
    def __init__(self, manager: "LLMManager", cfg: "ExtractorConfig", logger): ...
    async def extract(self, messages: list[dict], user: str) -> list[ExtractedFact]:
        """Build prompt over the look-back window, call the *dedicated* manager,
        validate/repair JSON, return confidence-scored ExtractedFacts. Pure."""
```

```python
# LongTermMemoryProvider (stateful scoring/persistence — extends Phase 7 provider)
async def _persist(self, ef: ExtractedFact) -> None:
    if ef.confidence < self.cfg.attribution.min_confidence:      # REQ-030
        return
    if not safety.is_safe(ef.summary):                           # CON-003
        return
    vec = (await self.embedder.embed([ef.summary]))[0]
    neighbours = await self.store.query(vec, k=1, where={"user": ef.target_user})
    novelty = 1.0 - (neighbours[0]["similarity"] if neighbours else 0.0)   # REQ-032
    if novelty <= self.cfg.scoring.dedup_novelty_max:            # REQ-033 merge
        await self._bump_importance(neighbours[0]["id"], evidence=ef.evidence)
        return
    importance_seed = 1
    if novelty <= self.cfg.scoring.importance_increment_below:   # REQ-034 related
        await self._bump_importance(neighbours[0]["id"])
    await self.store.upsert(                                      # REQ-035/038
        ids=[self._fact_id(ef)], vectors=[vec], documents=[ef.summary],
        metadatas=[{
            "user": ef.target_user, "category": ef.category, "source": "live",
            "confidence": ef.confidence, "sentiment": ef.sentiment,
            "novelty_at_write": novelty, "importance": importance_seed,
            "created_at": now(), "last_seen": now(),
            "embedder_id": self.embedder.id, "evidence": ef.evidence,
        }])
```

### 4.3 Registry
- `EXTRACTOR_REGISTRY["llm"] = LLMFactExtractor` (alongside `"heuristic"` from Phase 7).
- `ContextPipeline.from_config` builds the **dedicated extractor `LLMManager`** from
  `memory.long_term.extractor.llm` and injects it into the provider. It MUST NOT pass the
  message-generation manager (REQ-002).

## 5. Configuration Schema (additions under `memory.long_term.extractor`)

New Pydantic models under `kryten_llm/models/config.py`, referenced by the Phase 7 memory config.

```jsonc
{
  "context": {
    "providers": [
      {
        "type": "long_term_memory",
        "enabled": true,
        "extractor": {
          "type": "llm",                       // heuristic | llm  (REQ-014 parent swap-by-config)
          "heuristic_pregate": true,           // REQ-020 cheap gate before the LLM

          "llm": {                             // DEDICATED connection — never llm_providers  (REQ-001/002)
            "providers": {
              "extractor_local": {
                "type": "openai_compatible",
                "base_url": "http://localhost:1234/v1",
                "api_key": "${FACT_EXTRACTOR_KEY}",
                "model": "qwen2.5-7b-instruct",
                "temperature": 0.1,
                "max_tokens": 800,
                "timeout_seconds": 20,
                "max_retries": 2,
                "priority": 1
              }
            },
            "provider_priority": ["extractor_local"]
          },

          "structured_output": { "mode": "auto" },          // auto | json_schema | prompt  (REQ-014)

          "attribution": {
            "lookback_messages": 8,                          // REQ-023/030
            "min_confidence": 0.6                            // REQ-030
          },
          "sentiment": { "enabled": true },                  // REQ-031 (metadata only)

          "scoring": {
            "dedup_novelty_max": 0.08,                       // REQ-033 merge below this
            "importance_increment_below": 0.15,              // REQ-034 related-mention bump
            "importance_cap": 10000                          // REQ-036
          },

          "cadence": {
            "batch_max_size": 6,                             // REQ-021
            "batch_idle_seconds": 20,
            "max_facts_per_batch": 5                         // REQ-015
          },

          "retrieval_boost": {
            "importance_weight": 0.2,                        // REQ-037
            "recency_weight": 0.1
          }
        }
      }
    ]
  }
}
```

- Backwards compatibility: omitting `extractor` or setting `type: "heuristic"` reproduces Phase 7
  behaviour exactly. The `llm` subtree is only read when `type == "llm"`.
- Isolation is structural: the extractor's providers live under `memory.long_term.extractor.llm`
  and are loaded into a **separate** `LLMManager`; there is no reference to top-level
  `llm_providers` anywhere in the memory subtree (REQ-002).

## 6. Scoring Model — Worked Semantics

### 6.1 The three returned scores vs. the two derived scores
| Score | Who computes it | Range / meaning | Used for |
|-------|-----------------|-----------------|----------|
| `confidence` | Extractor LLM | 0–1, attribution certainty | Gate: drop `< min_confidence` (REQ-030) |
| `sentiment` | Extractor LLM | 0–1, 1 pos / 0 neg / 0.5 neutral | Stored metadata only (REQ-031) |
| `novelty` | Provider (embeddings) | 0–1, 1 novel / 0 duplicate | Dedup/merge + related-mention decisions (REQ-032–035) |
| `importance` | Provider (stateful) | integer counter, capped | Dedup salience + retrieval boost (REQ-036/037) |

`novelty` is precisely the "cardinality/similarity" score from the request, expressed so that
**higher = more novel**: `novelty = 1 − max_cosine_similarity(candidate, user's stored facts)`.

### 6.2 Decision table (single candidate)
| Condition | Action | `importance` effect |
|-----------|--------|---------------------|
| `confidence < min_confidence` | drop | none |
| summary fails safety re-check | drop | none |
| `novelty ≤ dedup_novelty_max` | **merge** (no insert) | `+1` on matched fact |
| `dedup_novelty_max < novelty ≤ importance_increment_below` | **insert** new | `+1` on nearest neighbour |
| `novelty > importance_increment_below` | **insert** new | seed `= 1` |

### 6.3 Why importance is a personality signal
Repeated low-novelty mentions (a user bringing up the same film/artist/opinion across sessions)
collapse into one fact whose `importance` climbs. High-importance facts (a) never duplicate the
prompt and (b) surface earlier in retrieval (REQ-037), so the bot's memory naturally reflects
what each user talks about *most*, not just *most recently*.

## 7. Implementation Phases

1. **7f-1 — Config + isolation.** Add `ExtractorConfig`/`ExtractorLLMConfig` Pydantic models; build
   the dedicated extractor `LLMManager` in `ContextPipeline.from_config`; assert no linkage to
   `llm_providers`. Unit-test isolation (REQ-001/002).
2. **7f-2 — Extractor core.** `LLMFactExtractor.extract` with prompt builder, look-back window,
   JSON schema + validation + single repair, `structured_output` auto-downgrade. Pure; unit-tested
   against recorded fixtures (no live LLM). (REQ-010–015)
3. **7f-3 — Scoring & persistence.** Extend `LongTermMemoryProvider`: confidence gate, mechanical
   novelty, dedup/merge, related-mention bump, importance cap, extended metadata. (REQ-030–038)
4. **7f-4 — Cadence & pre-gate.** Per-user batching, idle flush, heuristic pre-gate, off-critical-path
   background execution, bounded in-flight batches. (REQ-020–023, CON-004)
5. **7f-5 — Retrieval boost.** Blend importance + recency into ranking; expose weights. (REQ-037)
6. **7f-6 — Docs + example config.** Update `config.example.json`, memory docs, and the plain-English
   explainer. Ship behind opt-in.

## 8. Testing Strategy

- **Isolation (critical):** with only `memory.long_term.extractor.llm` configured and
  `llm_providers` pointing at a deliberately-broken endpoint, extraction still works and never
  touches the broken providers; and vice-versa (breaking the extractor endpoint never affects
  message generation). (REQ-001/002)
- **JSON contract:** valid schema parses; malformed JSON triggers exactly one repair; unrepairable
  output drops the batch and logs, never raises. Native-vs-prompt structured-output paths both
  produce identical `ExtractedFact` objects. (REQ-012–014)
- **Confidence gate:** facts below `min_confidence` never persisted; look-back window content is
  present in the prompt. (REQ-030)
- **Novelty/dedup/importance:** fixtures where a repeated fact yields `novelty ≈ 0` merges and
  increments importance (no new row); a related-but-distinct fact inserts and bumps a neighbour; a
  novel fact seeds importance = 1. Importance is capped. (REQ-032–036)
- **Retrieval boost:** given equal similarity, higher-importance / more-recent facts rank first;
  importance never overrides a much-higher semantic match. (REQ-037)
- **Cadence:** batches flush on size and on idle timeout; extraction runs off the critical path (a
  blocked extractor endpoint does not delay a simulated response). (REQ-021/022)
- **Safety:** PII in a message never reaches the LLM (pre-gate) and a summary containing PII is
  dropped at the re-check. (CON-001/003)
- **Contract parity:** `LLMFactExtractor` and `HeuristicFactExtractor` are interchangeable via
  config with no other code change (parent swap-by-config rule).

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Extractor silently borrows message-gen credentials/endpoint | Cost/isolation/security breach | Structural separation + explicit no-fallback test (REQ-002, isolation test). |
| LLM per message is expensive | Cost / rate limits | Heuristic pre-gate + per-user batching + small local model (REQ-020/021, GUD-003). |
| Malformed JSON from weak models | Dropped facts / crashes | Low temperature, native schema when available, one bounded repair, fail-open drop (REQ-013/014, GUD-001). |
| LLM misattributes facts in busy chat | Wrong-user memories | Look-back window + confidence gate; mechanical novelty can't fix attribution, so confidence is the guard (REQ-030). |
| Novelty scale confusion (1=novel vs 1=similar) | Inverted dedup logic | Single definition `novelty = 1 − cosine`; decision table §6.2; explicit tests. |
| Importance runaway / overflow | Pathological ranking | `importance_cap`, monotonic, log-normalised in ranking (REQ-036/037). |
| LLM copies PII into summary | Privacy leak into durable store | Safety re-check on summary before upsert; drop on fail (CON-003). |
| Hung extractor endpoint piles up tasks | Resource exhaustion | Per-provider timeout + bounded in-flight batches per user (CON-004). |

## 10. Open Questions

- Should `sentiment` eventually feed retrieval (e.g. prefer positive facts for friendly personas)
  or trigger selection? (Deferred; metadata-only for now per REQ-031.)
- Separate reranker/scoring model vs. the single extraction call — worth it once volume grows?
  (Deferred; single call + embedder is the MVP per scope.)
- Time-decay on `importance` (fade rarely-repeated facts) vs. hard cap only? (Ties into the parent's
  retention Open Question.)
- Should the LLM's advisory relatedness hint (if emitted) be logged for calibration against the
  mechanical `novelty`, to tune thresholds over time?
- Batch attribution: extract for the single focus user only, or let the LLM attribute facts to any
  author in the window (broader capture, higher misattribution risk)? (Leaning: window is context,
  facts limited to the focus user for MVP.)
