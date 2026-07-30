# PRD: Associative Memory

**Sprint**: 8 — `8-associative-memory`
**Status**: Planned (ready to start)
**Author**: (agent-drafted)
**Builds on**: Phase 7a–7f (`LongTermMemoryProvider`, pgvector/Chroma backends)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

---

## 1. Executive Summary

Kryten's long-term memory today answers a single question: *"what do I know about the
person currently talking?"* This sprint expands memory into **associative recall** —
topical, room-aware, thread-aware, and ambient retrieval — so the bot can reference what
*anyone* has said when it's relevant, react to genuinely new information, and volunteer
into conversations in a way that feels attentive and present rather than mechanical. The
flagship capability is **topic-scoped recall on auto-participation**: when the bot speaks
unprompted, it retrieves facts semantically similar to the current discussion regardless of
who said them.

## 2. Problem Statement

- **What.** The `LongTermMemoryProvider` retrieves only the speaker's facts
  (`where={"user": req.username}`) and formats them as a single flat list. It cannot bring
  up a relevant thing *someone else* said, cannot react to new disclosures, and its
  auto-participation messages are anchored only to the last literal line of chat.
- **Who.** The channel community — the bot feels like it has amnesia about the room and
  only "knows" whoever pinged it last. Auto-participation in particular reads as generic.
- **Why now.** pgvector storage now holds a substantial corpus of user facts; the data to
  power richer recall already exists. The gap is purely in *presentation/retrieval*, not
  collection.

## 3. Goals and Success Metrics

**Goals**
- Enable topical recall across all users during auto-participation.
- Add room-awareness, thread-aware query vectors, category-structured presentation,
  long-tail callbacks, novelty/contradiction signals, and an ambient mood vector.
- Do all of the above **without** weakening shadow-mute guarantees or introducing an
  un-gated privacy regression.

**Success metrics / acceptance**
- With all new flags off, provider output is byte-identical to Phase 7f (regression-proven).
- With topical recall on, an auto-participation turn on a themed discussion surfaces ≥1
  relevant fact from another (non-silenced) user, attributed by name.
- No fragment ever contains a currently shadow-muted user's fact (test-proven, fail-closed).
- New read paths stay within the existing `read_timeout_ms` fail-open budget (no p95
  regression on the response path).
- Test coverage ≥ 85% on new code.

## 4. User Stories

- *As a channel regular*, I want the bot to remember relevant things other people said, so
  it feels like it's actually part of our community, not a lookup bot.
- *As a lurker who just got shadow-muted*, I must **not** have the bot echo my old facts, so
  the mute is not silently defeated.
- *As an operator*, I want every cross-user behavior behind explicit, default-off flags, so
  I can adopt features incrementally and reason about privacy.
- *As a viewer in a busy room*, I want auto-participation to match the current mood and name
  people who are present, so the bot feels situationally aware.
- *As a returning user*, I want the bot to occasionally call back to something I mentioned
  long ago, so it feels like it genuinely remembers me.

**Edge cases**: empty history; cold-start (no facts); moderator bucket unavailable; a fact's
owner becomes silenced between write and read; message with no semantic content (emote/link).

## 5. Technical Architecture

All work extends the single `LongTermMemoryProvider`
([long_term_memory.py](../../kryten_llm/components/context/providers/long_term_memory.py)),
reusing its embedder, vector store, fail-open timeout wrapper, and Phase 7f boost ranking.

```
inbound msg ──▶ listener.filter_message (drops meta.shadow) ──▶ observe() [WRITE]
                                                             └─▶ trigger ─▶ provide() [READ]
                                                                              │
   ┌──────────────────────────────────────────────────────────────────────┘
   ▼  _provide_impl builds one or more RetrievalScope requests:
   • speaker (user_memory)            — today
   • topical (topical_memory)         — Sortie 1
   • room (room_memory)               — Sortie 2
   • ambient (ambient_memory)         — Sortie 7
   each scope ─▶ embed(query_source) ─▶ store.query(where) ─▶ ModerationGate filter ─▶ fragment
```

Key shared pieces (Sortie 0):
- **`RetrievalScope`** dataclass — `where`, `query_source`, `exclude_silenced`,
  `fragment_name`, `priority`.
- **`ModerationGate`** — read-only, TTL-cached view of currently-silenced users from
  `kryten_moderator_entries_{domain}_{channel}`.
- **`_build_where` `$in`/`$ne`** — parameterised operators in both store backends.

Data contracts: no vector-table schema change. Reads existing fact metadata
(`user`, `category`, `score`/importance, `created_at`) and the moderator's entries bucket.

## 6. Dependencies

- **kryten-py**: `KrytenClient`, `get_kv_store` (read-only bind of the moderator bucket).
- **kryten-moderator** (contract, not code): entries bucket name
  (`make_bucket_name(domain, channel)`) and entry `action ∈ {ban, smute, mute}`. Cross-link
  both repos' AGENTS.md.
- **Existing**: embedder + vector store (`kryten-llm[memory]` or `[pgvector]`).
- **Channel identity**: service must know `domain`/`channel` to resolve the moderator
  bucket; cross-user features stay disabled if unavailable.

## 7. Security and Privacy

- **Shadow-mute (hard requirement).** Write path already safe — `observe()` only runs on
  messages that survive `filter_message` (drops `meta.shadow==True`,
  [listener.py](../../kryten_llm/components/listener.py#L78)). New risk is on the **read**
  path: cross-user retrieval could resurface a user's facts learned *before* they were
  silenced. All cross-user fragments MUST exclude currently-silenced users and **fail
  closed** if the moderator bucket is unreadable.
- **Cross-user disclosure boundary.** `safety.py` gates *storage*, not *disclosure*.
  Surfacing user A's facts in user B's prompt is a new boundary → master `cross_user.enabled`
  flag, default off, documented in `docs/user-memory-explained.md` before release.
- **Injection (OWASP A03).** New `$in`/`$ne` where-clauses are fully parameterised; no string
  interpolation of usernames into SQL.
- **Least privilege.** kryten-llm binds the moderator bucket read-only and never writes
  moderator state.

## 8. Rollout Plan

- **Feature flags.** Every sortie ships default-off. Order of enablement in production:
  Sortie 0 (invisible) → 1 → 3 → 4 → 2 → 6 → 5 → 7.
- **Sequencing.** Sortie 0 is a hard dependency for 1, 2, 7 (anything cross-user). Sorties 3,
  4, 6 are speaker-scoped and independently shippable.
- **Monitoring.** Add counters for cross-user fragment emissions and moderation-gate
  fail-closed events; watch the provider's timeout rate for regressions.
- **Config/docs.** Update `config.example.json`, `docs/user-memory-explained.md`, and
  `CHANGELOG.md` per sortie.

## 9. Future Enhancements

- Importance/recency boost applied to cross-user (topical/room) results, not just speaker.
- Presence via the robot's userlist KV bucket (vs. the recent-message window heuristic).
- Model-based NLI for contradiction detection (Sortie 6 uses a heuristic v1).
- Learned/attention pooling for the window vector (Sortie 3 uses a mean centroid).

## 10. Open Questions

- **Sprint number.** No prior `docs/{N}-{sprint}/` folders exist; numbered `8` to continue
  from the team's existing "Phase 7" nomenclature. Confirm or renumber to `1`.
- **`silence_actions` default.** Only `smute`, or also `mute`/`ban`? (Defaulted to `smute`.)
- **Attribution privacy.** Is naming other users in-prompt (`[alice] ...`) acceptable, or
  should cross-user facts be anonymized? (Defaulted to attributed.)
- **Ambient scope.** Should ambient recall ever fire outside `auto_participation`?

## Sortie index

| # | Spec | Scope change | Query vector | Cross-user? |
|---|------|--------------|--------------|-------------|
| 0 | [SPEC-Sortie-0-foundation.md](SPEC-Sortie-0-foundation.md) | — | — | enables |
| 1 | [SPEC-Sortie-1-topic-recall.md](SPEC-Sortie-1-topic-recall.md) | drop user filter | message | yes |
| 2 | [SPEC-Sortie-2-room-awareness.md](SPEC-Sortie-2-room-awareness.md) | other active users | message | yes |
| 3 | [SPEC-Sortie-3-window-query.md](SPEC-Sortie-3-window-query.md) | speaker | last-N mean | no |
| 4 | [SPEC-Sortie-4-category-routing.md](SPEC-Sortie-4-category-routing.md) | speaker | message | no |
| 5 | [SPEC-Sortie-5-callback-resurfacing.md](SPEC-Sortie-5-callback-resurfacing.md) | speaker (opt. any) | message | optional |
| 6 | [SPEC-Sortie-6-novelty-signal.md](SPEC-Sortie-6-novelty-signal.md) | speaker | message | no |
| 7 | [SPEC-Sortie-7-ambient-mood.md](SPEC-Sortie-7-ambient-mood.md) | no filter | rolling mean | yes |

**Requirement ranges**: S0 040–049 · S1 050–059 · S2 060–069 · S3 070–079 · S4 080–089 ·
S5 090–099 · S6 100–109 · S7 110–119.
