# SPEC-Sortie-0: Foundation — safety & scope plumbing

**Sprint**: 8 — Associative Memory
**PRD**: [PRD-associative-memory.md](PRD-associative-memory.md)
**Status**: Implemented (checkpoint) — gate via moderator command API; all four gates green
**Estimate**: 4–6h
**Depends on**: Phase 7 (`LongTermMemoryProvider`, vector store backends)
**Blocks**: Sorties 1, 2, 7 (any cross-user retrieval)
**Requirements**: REQ-040 – REQ-049

---

## 1. Overview

Before any associative-recall feature can surface *other* users' facts, the provider needs a
shared safety substrate: a shadow-mute exclusion gate, a richer `where` translation
(`$in`/`$ne`) in both store backends, and scope plumbing so each later sortie can request a
retrieval scope without new `provide()` signatures. This sortie ships no user-visible
behavior on its own.

## 2. Scope and Non-Goals

**In scope**
- `ModerationGate` helper that queries the moderator's **command interface** (not KV), TTL-cached.
- `$in` / `$ne` operators in `_build_where` (pgvector) and pass-through for Chroma.
- `RetrievalScope` dataclass + scope-driven `_provide_impl`.
- `cross_user` + `moderation_gate` config blocks (default-safe).
- Thread `KrytenClient` + `domain`/`channel` into the provider via `deps`.
- Regression test locking in the write-path shadow-mute guarantee.

> **Design change (approved):** rather than reading the moderator's `kryten_moderator_entries_*`
> KV bucket directly (which couples kryten-llm to another service's internals + bucket-name
> normalization), the gate uses the moderator's **published command contract**
> `kryten.moderator.command` / `entry.list` via `KrytenClient.nats_request`. This is the
> ecosystem-sanctioned interface between services.

**Non-goals**
- No new user-facing fragment (that's Sorties 1+).
- No change to extraction/scoring (Phase 7f).
- No vector-table schema change.

## 3. Requirements

- **REQ-040** — `ModerationGate` obtains silenced users via the moderator command contract
  (`kryten.moderator.command` / `entry.list`) using `nats_request`; it never reads or writes
  the moderator's KV buckets.
- **REQ-041** — `_build_where` supports `$in` and `$ne` for `user` and metadata keys, fully
  parameterised; scalar-equality behavior unchanged (back-compat).
- **REQ-042** — Cross-user retrieval excludes users whose current action ∈ `silence_actions`
  (default `{"ban", "smute", "mute"}`).
- **REQ-043** — When the moderation bucket is unreadable and `fail_closed` is true, any
  cross-user fragment returns empty rather than risk surfacing a silenced user.
- **REQ-044** — Speaker-scoped retrieval is unaffected by the gate (no added latency, no
  fail-closed).
- **REQ-045** — The silenced-user set is cached with `cache_ttl_s` TTL per channel.
- **REQ-046** — All cross-user behavior is gated by `cross_user.enabled` (default false);
  with it false, provider output is identical to Phase 7f.
- **REQ-047** — Regression: a `meta.shadow=True` message never reaches `observe()`.

## 4. Design

### 4.1 ModerationGate

Kryten-Moderator exposes moderation state on its command subject `kryten.moderator.command`
([nats_handler.py](../../../kryten-moderator/kryten_moderator/nats_handler.py)) — including
`entry.list`, which returns all entries (each with an `action ∈ {ban, smute, mute}`). The gate
queries that contract via `KrytenClient.nats_request` and never touches the moderator's KV.

```python
class ModerationGate:
    """TTL-cached view of currently-silenced users, via the moderator command API.

    silenced_users() returns None when the moderator cannot be reached / replies
    with failure, so the caller can apply its fail-closed policy.
    """

    def __init__(self, client, domain, channel, *,
                 silence_actions=frozenset({"ban", "smute", "mute"}),
                 cache_ttl_s=10.0, request_timeout_s=2.0): ...

    async def silenced_users(self) -> frozenset[str] | None:
        """Lowercased usernames under a silencing action, or None on failure."""
        resp = await self._client.nats_request(
            "kryten.moderator.command",
            {"service": "moderator", "command": "entry.list",
             "domain": self._domain, "channel": self._channel},
            timeout=self._request_timeout_s,
        )
        # resp = {"success": bool, "data": {"entries": [{"username", "action", ...}]}}
```

- `silence_actions` default `{ban, smute, mute}` (approved): the bot suppresses the facts of
  anyone under **any** active moderation action, not just shadow mutes.
- On timeout / `success=False` / malformed reply → return `None` (caller fails closed).

### 4.2 Where operators

Extend `_build_where`
([vector_store.py](../../kryten_llm/components/memory/vector_store.py#L538)):

```python
# {"user": {"$in": [...]}}  ->  username = ANY($n)
# {"user": {"$ne": v}}      ->  username <> $n
# metadata {"$in"/"$ne"}    ->  (metadata ->> $k) = ANY($v) / <> $v
```

Chroma supports `$in`/`$ne` natively — pass through. Scalars keep current meaning.

### 4.3 RetrievalScope + gate application

```python
@dataclass
class RetrievalScope:
    where: dict[str, Any] | None
    query_source: Literal["message", "username", "window", "ambient"]
    exclude_silenced: bool
    fragment_name: str
    priority: int
```

```python
if scope.exclude_silenced:
    silenced = await self._mod_gate.silenced_users()
    if silenced is None:                       # bucket down
        return []                              # fail-closed for THIS fragment
    filtered = [r for r in filtered
                if r["metadata"].get("user", "").lower() not in silenced]
```

Speaker scope sets `exclude_silenced=False` (speaker already passed the live `meta.shadow`
filter).

## 5. Implementation Plan

**New**
- `kryten_llm/components/memory/moderation_gate.py` — `ModerationGate`.

**Modify**
- `kryten_llm/components/memory/vector_store.py` — `_build_where` `$in`/`$ne` (pgvector);
  verify Chroma pass-through.
- `kryten_llm/components/context/providers/long_term_memory.py` — add `RetrievalScope`,
  refactor `_provide_impl` to be scope-driven, construct `ModerationGate` from config, add
  gate-filter step.
- `kryten_llm/models/config.py` — `CrossUserConfig`, `ModerationGateConfig`.
- `config.example.json` — new blocks (below).

**Config**

```jsonc
"cross_user": { "enabled": false },
"moderation_gate": {
  "enabled": true,
  "silence_actions": ["ban", "smute", "mute"],
  "cache_ttl_s": 10,
  "request_timeout_s": 2.0,
  "fail_closed": true
}
```

`domain`/`channel` come from existing channel config (`config.channels[0]`, inherited from
kryten-py). The `KrytenClient` is threaded into the provider via `deps`. If the client or
channel identity is unavailable, cross-user retrieval stays disabled with a one-time warning.

## 6. Testing Strategy

**Unit**
- `_build_where` emits correct parameterised SQL for `$in`/`$ne`; a username with `';DROP`
  is bound, not interpolated.
- `ModerationGate.silenced_users()` returns the smuted set; returns `None` on KV error;
  second call within TTL does not re-read.
- `_provide_impl` drops silenced-user results; fails closed when gate returns `None` and
  `fail_closed=True`.

**Regression**
- Shadow-muted inbound message → `observe()` not called (mock pipeline).

**Back-compat**
- `cross_user.enabled=false` → provider output matches the Phase 7f golden fragment.

**Coverage target**: ≥ 85% on new code.

## 7. Acceptance Criteria

- [ ] With defaults, behavior identical to today (cross-user off).
- [ ] With `cross_user` on + mocked moderator bucket, a smuted user's facts never appear.
- [ ] Killing the moderator bucket makes cross-user fragments vanish (not error); speaker
      fragment still served.
- [ ] `$in`/`$ne` unit tests pass with parameterised SQL.
- [ ] Shadow-mute write-path regression test passes.
- [ ] Coverage ≥ 85%.

## 8. Rollout

- Ships default-off/safe; no runtime behavior change on enable of `moderation_gate` alone.
- Add metric counters: cross-user gate lookups, fail-closed events.
- No migration.

## 9. Documentation

- Code docstrings on `ModerationGate` and `RetrievalScope`.
- `config.example.json` comments for new blocks.
- Note in `docs/user-memory-explained.md` that cross-user disclosure is introduced here and
  gated.
- Cross-link kryten-moderator AGENTS.md (entries bucket contract dependency).
- `CHANGELOG.md`: unreleased entry for the foundation plumbing.
