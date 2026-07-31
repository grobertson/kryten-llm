# SPEC-Sortie-3: `last_seen` Field Consistency & Backfill

**Sprint**: 20 — Temporal Fact Awareness
**PRD**: [PRD-temporal-awareness.md](PRD-temporal-awareness.md)
**Status**: Planned
**Estimate**: 2h
**Depends on**: Sortie 1 (`last_seen` in `_upsert_facts` for new facts); Sprint 10 (CLI
  command pattern for memory subcommands)
**Requirements**: REQ-415 – REQ-419

---

## 1. Overview

Sortie 1 ensures all *new* heuristic-mode facts receive `last_seen`. This sortie handles
*existing* facts in deployed stores that predate Sprint 20 and have no `last_seen` field.
A one-time backfill CLI command sets `last_seen = created_at` (or `datetime.now()` if no
`created_at`) for every fact missing `last_seen`. Also verifies the field is written in the
LLM-mode paths and documents any remaining gaps.

---

## 2. Scope and Non-Goals

**In scope**: `kryten-llm memory backfill-last-seen` CLI command; verification that
LLM-mode `_persist` and `_bump_importance` correctly write `last_seen`; tests.

**Non-goals**: Migration of `confidence`, `importance`, or any other metadata field.
No new sweeper. No changes to the write path (Sortie 1 already handled new facts).

---

## 3. Requirements

- **REQ-415** — `kryten-llm memory backfill-last-seen [--config CONFIG] [--dry-run]`
  fetches all facts from the store, identifies those without a `last_seen` field, and
  sets `last_seen = created_at` (or `datetime.now(timezone.utc).isoformat()` if no
  `created_at`).
- **REQ-416** — `--dry-run` logs what would be updated without writing. Prints
  `"[dry-run] Would backfill N fact(s)."` Exit code 0.
- **REQ-417** — Idempotent: facts that already have `last_seen` are skipped.
- **REQ-418** — LLM-mode `_persist` writes `last_seen = now` in the metadata dict for
  new facts. `_bump_importance` already writes `last_seen` (this requirement is a
  *verification* — audit the code; add it if missing, no-op if already present).
- **REQ-419** — Backfill prints a summary: `"Backfilled N fact(s). M already had last_seen."`.
  Errors logged per-fact; never crash.

---

## 4. Design

### CLI command

```python
# In kryten_llm/__main__.py — memory subparser group
parser_backfill = memory_sub.add_parser(
    "backfill-last-seen",
    help="Backfill last_seen timestamp for facts missing it (one-time migration)"
)
parser_backfill.add_argument("--dry-run", action="store_true",
                             help="Preview without writing (REQ-416)")
parser_backfill.set_defaults(func=_cmd_backfill_last_seen)

async def _cmd_backfill_last_seen(args: argparse.Namespace, config: "LLMConfig") -> None:
    from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider

    ltm = _get_ltm_provider(config)
    if ltm is None:
        print("No long_term_memory provider configured.", file=sys.stderr)
        sys.exit(1)

    all_records = await ltm._store.get_all()
    to_backfill = [r for r in all_records if not r.get("metadata", {}).get("last_seen")]
    already_present = len(all_records) - len(to_backfill)

    if args.dry_run:
        print(f"[dry-run] Would backfill {len(to_backfill)} fact(s). "
              f"{already_present} already had last_seen.")
        return

    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    for r in to_backfill:
        try:
            meta = dict(r.get("metadata", {}))
            meta["last_seen"] = meta.get("created_at") or now
            await ltm._store.update_metadata(ids=[r["id"]], metadatas=[meta])
            updated += 1
        except Exception as exc:
            logger.error("backfill: failed for id=%s: %s", r.get("id"), exc)

    print(f"Backfilled {updated} fact(s). {already_present} already had last_seen.")
```

### LLM-mode path audit

Check `_persist` in `long_term_memory.py`:
```python
meta: dict[str, Any] = {
    ...
    "created_at": now,
    "last_seen": now,     # REQ-418: verify this is present (Sortie 1 adds it to heuristic;
                          # LLM mode _persist must also write it)
    ...
}
```

Check `_bump_importance` in `long_term_memory.py`:
```python
if last_seen:
    meta["last_seen"] = last_seen   # already present (REQ-034 context)
```

Both should already be in place; REQ-418 is a code-review gate, not a new implementation.
If either is missing, add it.

---

## 5. Implementation Plan

**Modify** `kryten_llm/__main__.py`:
- Add `backfill-last-seen` subcommand.

**Audit** `kryten_llm/components/context/providers/long_term_memory.py`:
- Verify `_persist` writes `last_seen` in the new-fact metadata dict (add if missing).
- Verify `_bump_importance` writes `last_seen` (it should already; confirm).

---

## 6. Testing Strategy

- Store with 3 facts: 2 missing `last_seen`, 1 present.
- `backfill-last-seen`: updates 2 facts; reports `"Backfilled 2 fact(s). 1 already had last_seen."`.
- `--dry-run`: no writes; reports `"[dry-run] Would backfill 2..."`.
- Re-run after backfill: `"Backfilled 0 fact(s). 3 already had last_seen."` (idempotent).
- Facts with `created_at` get `last_seen = created_at`.
- Facts with no `created_at` get `last_seen = now`.
- `update_metadata` error on one fact: logged, others still updated.

---

## 7. Acceptance Criteria

- [ ] `backfill-last-seen` updates facts missing `last_seen`.
- [ ] Idempotent: re-run has no effect.
- [ ] `--dry-run` no writes.
- [ ] Uses `created_at` as `last_seen` when available.
- [ ] `_persist` writes `last_seen` (verified by code audit + test).
- [ ] `_bump_importance` writes `last_seen` (verified by code audit + test).

---

## 8. Rollout

One-time operator command for existing deployments:
```
kryten-llm memory backfill-last-seen --config /etc/kryten/kryten-llm/config.json
```
Run `--dry-run` first to preview. Safe to skip if store is new (Sortie 1 covers new facts).

---

## 9. Documentation

`CHANGELOG.md` entry.
Add one-time migration note to `DEPLOYMENT.md` under "Upgrading to Sprint 20".
