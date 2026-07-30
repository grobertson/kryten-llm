# PRD: Memory Quality & Observability

**Sprint**: 9 — `9-memory-quality`
**Status**: Current (N) — active sprint; fully specified
**Author**: (agent-drafted)
**Builds on**: Sprint 8 (Associative Memory)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

---

## 1. Executive Summary

Sprint 8 introduced associative recall (topical, room, ambient, callbacks, novelty). Sprint 9
**hardens and sharpens** it for production: it applies the Phase 7f importance/recency boost
to cross-user results, upgrades the heuristic placeholders (window pooling, contradiction
detection) to higher-quality implementations, replaces the room-awareness activity heuristic
with authoritative presence from the robot's userlist, and adds the observability needed to
tune all of it safely. No new memory *surfaces* — this sprint makes the Sprint 8 surfaces
smarter and measurable.

## 2. Problem Statement

- **What.** Sprint 8 shipped several deliberately-simple v1 mechanisms: cross-user retrieval
  ranks by raw similarity only (no importance/recency boost), the conversation-window vector
  is a plain mean, contradiction detection is a keyword heuristic, and room-awareness infers
  presence from recent chat rather than the real userlist. There is also no memory-specific
  telemetry, so operators cannot see what the memory system is injecting or why.
- **Who.** Operators (can't tune or trust the feature) and the community (lower-quality
  recall, occasional irrelevant pulls).
- **Why now.** These are the known follow-ups explicitly deferred in the Sprint 8 PRD §9;
  doing them right after Sprint 8 lands avoids a quality/observability gap in production.

## 3. Goals and Success Metrics

**Goals**
- Cross-user (topical/room/ambient) results ranked with the same importance+recency boost as
  speaker facts.
- Authoritative presence for room-awareness from the robot userlist KV.
- Embedding-based contradiction detection replacing the keyword heuristic.
- Higher-quality window query vector (recency-weighted / lightweight attention pooling).
- Memory observability: metrics + optional per-turn fragment trace.

**Success metrics**
- Boost ranking applied to cross-user results (test-proven ordering change vs. pure
  similarity).
- Room-awareness uses live userlist when available, falling back to the Sprint 8 heuristic on
  KV failure (fail-open).
- Contradiction precision improves on a labeled fixture set vs. the heuristic baseline.
- New telemetry exposes per-fragment emission counts, gate fail-closed events, and retrieval
  latency percentiles.
- All flags default to Sprint 8 behavior; coverage ≥ 85% on new code.

## 4. User Stories

- *As an operator*, I want metrics on what memory injects and how long it takes, so I can tune
  thresholds and catch regressions.
- *As a community member*, I want the bot to surface the *most salient* relevant fact, not
  just the most textually similar, so recall feels intelligent.
- *As an operator*, I want room-awareness to reflect who is actually in the channel, so the
  bot doesn't reference someone who left.
- *As a community member*, I want the bot to correctly notice when I contradict something I
  said before, so it feels attentive rather than pedantic about coincidental word overlap.

## 5. Technical Architecture

All work extends the `LongTermMemoryProvider` and shared Sprint 8 plumbing
(`RetrievalScope`, `ModerationGate`). New reads: the robot userlist KV bucket
`cytube_{safe_domain}_{channel}_userlist` (key `users`), bound read-only — Kryten-Robot owns
it. New telemetry integrates with the existing `health_monitor` / `metrics_server`
components.

```
RetrievalScope results ─▶ [S1 boost re-rank] ─▶ gate ─▶ fragment
room scope ─▶ [S2 userlist presence] ──────────────────┘
provide() ─▶ [S3 contradiction via embedding] ─▶ memory_signal
observe() ─▶ window/mood pooling ◀─ [S4 attention pooling]
all paths ─▶ [S5 metrics + optional trace]
```

## 6. Dependencies

- **Sprint 8** merged (hard dependency — extends its scopes and gate).
- **kryten-py**: `kv_get` for userlist read; existing embedder for contradiction/pooling.
- **Kryten-Robot** (contract): userlist bucket name/shape (`users` key). Cross-link AGENTS.md.
- **health_monitor / metrics_server**: extend existing Prometheus surface.

## 7. Security and Privacy

- Cross-user boost (S1) operates on already-gated result sets — no new disclosure path; the
  Sprint 8 shadow-mute gate still runs after re-ranking.
- Userlist presence (S2) reads robot state read-only; presence alone is not a fact and is not
  stored.
- Observability (S5) must **not** log fact contents or usernames at default levels — counts
  and latencies only; any content trace is behind an explicit debug flag and respects the
  shadow-mute/privacy posture.

## 8. Rollout Plan

- Every sortie default-off or defaulting to Sprint 8 behavior.
- Order: S5 (observability first, to measure the rest) → S1 → S2 → S4 → S3.
- Monitor new metrics for regressions after each enable.
- Update `config.example.json`, docs, `CHANGELOG.md` per sortie.

## 9. Future Enhancements

- Learned re-ranker (cross-encoder) over candidate facts.
- Presence-weighted ambient mood (weight the mood vector toward present users).
- Confidence/verification scoring for facts (feeds Sprint 12 roadmap).

## 10. Open Questions

- Should contradiction detection (S3) gate on a minimum stored-fact count per user to avoid
  false positives during cold-start?
- Metrics cardinality: per-fragment-type counters only, or also per-channel labels?
- Do we expose retrieval latency as a histogram or summary in `metrics_server`?

## Sortie index

| # | Spec | Summary | REQ |
|---|------|---------|-----|
| 1 | [SPEC-Sortie-1-cross-user-boost.md](SPEC-Sortie-1-cross-user-boost.md) | Importance+recency boost on cross-user results | 120–129 |
| 2 | [SPEC-Sortie-2-userlist-presence.md](SPEC-Sortie-2-userlist-presence.md) | Authoritative presence from robot userlist KV | 130–139 |
| 3 | [SPEC-Sortie-3-embedding-contradiction.md](SPEC-Sortie-3-embedding-contradiction.md) | Embedding-based contradiction detection | 140–149 |
| 4 | [SPEC-Sortie-4-attention-pooling.md](SPEC-Sortie-4-attention-pooling.md) | Recency/attention-weighted window & mood pooling | 150–159 |
| 5 | [SPEC-Sortie-5-memory-observability.md](SPEC-Sortie-5-memory-observability.md) | Metrics + optional per-turn fragment trace | 160–169 |
