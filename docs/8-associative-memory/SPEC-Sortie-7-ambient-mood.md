# SPEC-Sortie-7: Ambient / mood vector

**Sprint**: 8 — Associative Memory
**PRD**: [PRD-associative-memory.md](PRD-associative-memory.md)
**Status**: Planned
**Estimate**: 4–6h
**Depends on**: Sortie 0 (gate, cross-user); pairs with Sortie 3 (window pooling)
**Requirements**: REQ-110 – REQ-119

---

## 1. Overview

Auto-participation should match the room's *current vibe*, not just the last literal line.
Maintain a **rolling mean embedding** of recent channel chatter (the "mood vector") and, when
the bot volunteers a message, retrieve facts near that centroid to seed a reply that fits the
ambient mood. This is the most "present in the room" feature and the loosest — for
`auto_participation` only.

## 2. Scope and Non-Goals

**In scope**: per-channel EWMA mood vector on the observe path; warm-up gate; ambient
whole-room retrieval on auto-participation; shadow-mute exclusion (double coverage).

**Non-goals**: firing outside auto-participation (config-guarded); persisting the mood vector
across restarts.

## 3. Requirements

- **REQ-110** — Per-channel EWMA mood vector updated on accepted messages only.
- **REQ-111** — Shadow-muted messages never update the mood vector.
- **REQ-112** — Mood not used until `warmup_messages` reached.
- **REQ-113** — Ambient retrieval fires only for `fire_on` types (default `auto_participation`).
- **REQ-114** — Silenced users excluded from ambient results (fail-closed).
- **REQ-115** — Emits `ambient_memory` at low priority; trimmed first under budget.
- **REQ-116** — Off unless `cross_user.enabled && ambient.enabled`.
- **REQ-117** — Mood state is a single bounded vector per channel (no unbounded growth).

## 4. Design

### 4.1 Mood vector (observe path)

EWMA of message embeddings, per channel, off the critical response path:

```python
# on each ACCEPTED (non-shadow) message:
mood = normalize((1 - alpha) * mood + alpha * embed(message))
```

Reuses embeddings from the write/extraction path where available. Only messages passing
`filter_message` contribute (shadow-muted never shape the mood). Bounded: one vector + warm-up
counter per channel.

### 4.2 Retrieval (read path)

On an auto-participation turn (warmed up), query with the mood vector across all users:

```python
scope = RetrievalScope(
    where=None,                    # whole-room
    query_source="ambient",        # EWMA mood vector
    exclude_silenced=True,         # MANDATORY, fail-closed
    fragment_name="ambient_memory",
    priority=ambient.priority,
)
```

Diffuse vector → lower `min_similarity`, small `top_k`, low priority (trimmed first).
Attribution `• [user] fact` like Sortie 1.

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — mood-vector state + EWMA update in `observe`; `query_source="ambient"`
  builder; ambient scope branch gated on trigger type.
- `models/config.py` — `AmbientConfig`.
- `config.example.json` — `ambient` block.

**Config**
```jsonc
"ambient": {
  "enabled": false,
  "alpha": 0.15,
  "warmup_messages": 15,
  "top_k": 3,
  "min_similarity": 0.20,
  "fire_on": ["auto_participation"],
  "priority": 26
}
```

## 6. Testing Strategy

- Mood converges toward the topic of a run of on-topic messages (cosine increases).
- Shadow-muted message does not move the mood vector.
- No ambient fragment before warm-up.
- Fires on `auto_participation`, not `mention`.
- Smuted user excluded from ambient results.
- Off by default.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] After warm-up, an unprompted message reflects the room's recent mood.
- [ ] Never sourced from or naming a silenced user.
- [ ] Disabled by default.

## 8. Rollout

- Enable last, after Sortie 0 (+ ideally Sortie 3). Requires `cross_user.enabled`.
- Low priority so a bad ambient pull is cheaply trimmed. Monitor ambient-emission counter and
  timeout rate.

## 9. Documentation

- `config.example.json` comments (mood vector, warm-up, `alpha` tuning).
- `docs/user-memory-explained.md`: ambient recall + privacy (double shadow-mute coverage).
- `CHANGELOG.md` entry.
