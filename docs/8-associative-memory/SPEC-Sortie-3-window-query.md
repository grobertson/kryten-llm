# SPEC-Sortie-3: Conversation-window query vector

**Sprint**: 8 — Associative Memory
**PRD**: [PRD-associative-memory.md](PRD-associative-memory.md)
**Status**: Implemented (checkpoint) — 7 tests green; default query_mode=message
**Estimate**: 2–4h
**Depends on**: none (standalone); orthogonal quality boost for Sorties 1, 2
**Requirements**: REQ-070 – REQ-079

---

## 1. Overview

Retrieval today embeds only `req.message` (a single line, often a reaction/emote/link with
little semantic content). Embed a **window** of the last *N* messages and use that mean as the
query vector, so retrieval reflects the ongoing topic. Applies to every scope, so it's a
cross-cutting quality lever, not a new fragment.

## 2. Scope and Non-Goals

**In scope**: `query_mode="window"`, mean pooling, optional recency weighting, embedding
reuse, back-compat default.

**Non-goals**: learned/attention pooling; changing `relate_to_message=false` (username mode).

## 3. Requirements

- **REQ-070** — `query_mode="window"` builds the query vector from the mean of the last
  `window_size` messages.
- **REQ-071** — Empty window falls back to the single-message vector.
- **REQ-072** — Optional geometric recency weighting via `window_recency_weight`.
- **REQ-073** — Embeddings for the current message are reused, not recomputed.
- **REQ-074** — `query_mode` defaults to `"message"`; window mode is opt-in and back-compat.
- **REQ-075** — Window mode applies uniformly to speaker/topical/room scopes.

## 4. Design

Add `query_source="window"` (Sortie 0 `RetrievalScope`). Window vector = mean-pooled
embedding of the last *N* cleaned messages.

```python
texts = [m["message"] for m in recent_messages(window_size)][-window_size:]
if not texts:
    return message_vector
vecs = await self._embedder.embed(texts)
window_vec = weighted_mean(vecs, window_recency_weight)   # 0 = plain centroid
```

- Recency weighting: geometric decay so the newest line dominates without being the only
  signal. `0.0` = plain mean.
- Cost mitigation: cap `window_size`, reuse the current message's embedding, optional bounded
  `text->vector` LRU.

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — window vector builder in the `query_source` switch; embedding reuse.
- `models/config.py` — extend retrieval config with `query_mode`, `window_size`,
  `window_recency_weight`.
- `config.example.json` — retrieval block additions.

**Config**
```jsonc
"retrieval": {
  "top_k": 5, "relate_to_message": true, "min_similarity": 0.25,
  "query_mode": "message",        // "message" | "window"
  "window_size": 6,
  "window_recency_weight": 0.0
}
```

## 6. Testing Strategy

- 6-message window about "kung fu films" retrieves a kung-fu fact even when the last line is
  ":thumbsup:".
- Empty history → identical to message mode.
- `window_recency_weight=0` equals numpy mean within tolerance.
- Default config never calls the window builder.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Window mode improves retrieval on link/emote-terminated threads.
- [ ] No p95 regression against the fail-open timeout budget.
- [ ] Default (message mode) output unchanged.

## 8. Rollout

- Default-off; enable per channel. May need a small `min_similarity` retune (window matches
  are broader) — document.
- No cross-user exposure; no Sortie 0 dependency.

## 9. Documentation

- `config.example.json` comments (note the broader-match trade-off).
- `docs/user-memory-explained.md`: window vs. message query modes.
- `CHANGELOG.md` entry.
