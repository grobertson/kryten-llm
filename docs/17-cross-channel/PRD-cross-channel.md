# PRD: Multi-Instance Shared Memory

**Sprint**: 17 — `17-cross-channel` *(scope revised 2026-07-30)*
**Status**: Complete ✅ — implemented 2026-07-30 (Sorties 1–3, REQ-340–345)
**Builds on**: Sprints 8–15
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

> **Scope revision (2026-07-30)**: The original "cross-channel knowledge sharing" framing was
> over-engineered for the actual deployment. The real problem is two kryten-llm instances in
> **the same channel** sharing a single fact store safely. No federation, no consent gates,
> no cross-channel privacy architecture required — just concurrency-safe shared access to one
> memory backend. Sprint is substantially smaller than originally planned.

---

## 1. Problem Statement

The production deployment runs two kryten-llm instances against the same CyTube channel:

- **Primary bot** — speaks on triggers and auto-participation; conversationally interactive;
  uses a fast local model. Observes and learns from the full chat stream continuously.
- **Secondary bot** — responds only when directly addressed (questions, trivia requests,
  "help me out here?"); uses a larger, more capable model for deep recall on films,
  television, and 20th-century pop culture.

Today each instance maintains a **separate, siloed fact store**. The secondary bot starts
every interaction cold — it has no knowledge of a user's preferences, history, or personality
despite the primary bot having built months of context on them. A user who just told the
primary bot their favourite Kubrick film gets no recognition from the secondary bot when they
ask it a Kubrick trivia question five minutes later.

The fix is architecturally simple: **both instances point at the same fact store.** The only
non-trivial concern is write concurrency — two processes writing to an embedded Chroma
directory simultaneously will corrupt the index. The solution (Chroma server mode or
pgvector) is already documented in `config.example.json`.

**Who benefits**: operators (secondary bot is immediately useful to users it meets for the
first time), the community (the two bots feel like they share a brain, not two strangers),
and the project (zero new architecture — just a validated deployment pattern).

---

## 2. User Stories

- *As an operator*, I want both bot instances to share the same fact store so the secondary
  bot has full context on users it hasn't personally spoken with.
- *As an operator*, I want a clear, tested deployment guide for running two instances against
  a shared store without data corruption risk.
- *As a community member*, I want the trivia bot to recognise me without me re-introducing
  myself every time I address it directly.
- *As a maintainer*, I want the shared-store pattern validated by a concurrency test so
  I can deploy it with confidence.

---

## 3. Feasibility / Technical Read

**The core constraint is Chroma's embedded `PersistentClient`**: it is strictly
single-process. Two instances sharing a `store.path` in embedded mode will corrupt the
collection. The fix is already in the config:

**Option A — Chroma server mode** (preferred for local deployments):
```bash
# Run once:
chroma run --path ./data/chroma --port 8000
# Both bot configs:
"store": { "backend": "chroma", "http_host": "localhost", "http_port": 8000 }
```

**Option B — pgvector** (preferred for production):
Both instances use the same `dsn` / `dsn_env`. Postgres handles concurrent writers natively.
No additional setup beyond what a single-instance deployment already requires.

**Write rate**: the primary bot writes facts continuously (full observation stream); the
secondary writes infrequently (it only responds when spoken to, so it observes fewer
messages). Concurrency pressure is low.

**`forget.user` semantics**: both bots subscribe to `kryten.llm.command`. A `forget.user`
command reaches the shared store regardless of which bot receives it — erasure is
automatically complete. No cascade logic is needed.

**Bot self-observation**: the secondary bot's persona should be listed in the primary bot's
`ignored_users` config (and vice versa) to prevent each bot from extracting facts about the
other's character.

**Risk**: very low. This is a configuration + validation change, not an architecture change.
The worst failure mode is operator misconfiguration (using embedded Chroma with two
instances), which is caught immediately by observable corruption.

---

## 4. Scope (candidate sorties)

1. **Concurrency validation test** — integration test: two concurrent `LongTermMemoryProvider`
   writers against a shared Chroma HTTP store; assert no data loss, correct user isolation,
   and that `forget.user` from either instance erases the fact from the shared store.
2. **Deployment guide** — `docs/MULTI_INSTANCE.md`: shared-store deployment patterns for
   Chroma server mode and pgvector; `ignored_users` guidance for bot-on-bot exclusion;
   example systemd units for both instances.
3. **Store-mode observability** *(optional)* — expose `store_backend` and `store_mode`
   (embedded vs. server) in the `/metrics` endpoint so operators can confirm the shared-store
   pattern is active.

---

## 5. Open Questions

- Should the secondary bot have a read-only store connection? It mostly reads; a read-only
  flag would be safer but requires a config option and store abstraction change. Probably
  over-engineering given the low write rate — revisit at promotion if write contention is
  observed in practice.
- Can the Chroma HTTP server concurrency test run in CI, or does it require a live `chroma
  run` process? If the latter, it may be a manual deployment-time check only.
- Should `ignored_users` guidance be promoted to a first-class config section with clearer
  semantics (e.g. `bot_peers: [...]` that automatically adds to ignored_users and suppresses
  fact extraction)?

**REQ reservation**: REQ-340+ (finalised at promotion).
