# SPEC-Sortie-6: Novelty / contradiction signal

**Sprint**: 8 — Associative Memory
**PRD**: [PRD-associative-memory.md](PRD-associative-memory.md)
**Status**: Planned
**Estimate**: 2–4h
**Depends on**: none (speaker-scoped, read side of the existing path)
**Requirements**: REQ-100 – REQ-109

---

## 1. Overview

When a user says something whose embedding is **far** from everything stored about them,
that's a signal of *new information* the bot can react to ("wait, you never mentioned you play
guitar"). A near-duplicate-but-opposite fact hints at a **contradiction/update**. This adds a
lightweight read-time *signal fragment* — it does not store facts.

## 2. Scope and Non-Goals

**In scope**: novelty signal from the existing top-1 speaker distance; shallow contradiction
heuristic; `memory_signal` fragment.

**Non-goals**: model-based NLI/entailment; cross-user novelty; writing/editing facts.

## 3. Requirements

- **REQ-100** — Novelty computed from the existing top-1 speaker distance (no extra query).
- **REQ-101** — Novel signal emitted when similarity < `novelty_max_similarity`.
- **REQ-102** — Contradiction signal emitted when similarity > `contradiction_min_similarity`
  and a polarity flip is detected.
- **REQ-103** — Emits a `memory_signal` fragment; never mutates stored facts.
- **REQ-104** — Disabled by default; no fragment when off.
- **REQ-105** — Fully inside the fail-open timeout budget (adds no store round-trip).

## 4. Design

During `provide()`, reuse the nearest stored speaker fact (already fetched):

```python
sim = 1.0 - top_speaker_result.distance          # existing _similarity mapping
if sim < novelty.novelty_max_similarity:
    signal = ("novel", message_summary)
elif sim > novelty.contradiction_min_similarity and polarity_differs(...):
    signal = ("contradiction", nearest.document)
```

- Novelty is free: it's the top-1 distance already computed.
- Contradiction v1 is shallow: high similarity + a simple negation/polarity heuristic (reuse
  the extractor's keyword regexes where possible).
- Emits a short `memory_signal` fragment to steer tone; it does **not** assert the fact as
  truth (the write path still decides storage).

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — compute signal from the existing speaker result; polarity helper;
  emit `memory_signal` fragment.
- `models/config.py` — `NoveltyConfig`.
- `config.example.json` — `novelty` block.

**Config**
```jsonc
"novelty": {
  "enabled": false,
  "novelty_max_similarity": 0.35,
  "contradiction_min_similarity": 0.80,
  "priority": 28,
  "novel_label": "This seems new for {user}",
  "contradiction_label": "This may update what you knew"
}
```

## 6. Testing Strategy

- Message about an unstored hobby → `novel` signal.
- Message contradicting a stored preference (high sim + negation) → `contradiction` signal.
- Routine on-topic message → no signal.
- No extra `store.query` for the signal (reuses speaker result — assert call count).
- Off by default.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Bot can react to a genuine first-time disclosure with no measurable latency increase.
- [ ] No fact is fabricated or stored as a side effect.
- [ ] Disabled by default.

## 8. Rollout

- Default-off; enable per channel. No cross-user exposure; no Sortie 0 dependency.

## 9. Documentation

- `config.example.json` comments.
- `docs/user-memory-explained.md`: novelty/contradiction signal semantics (read-only).
- `CHANGELOG.md` entry.
