# SPEC-Sortie-2: Compaction CLI Command

**Sprint**: 19 — Semantic Fact Compaction
**PRD**: [PRD-fact-compaction.md](PRD-fact-compaction.md)
**Status**: Planned
**Estimate**: 1–2h
**Depends on**: Sortie 1 (`CompactionSweeper` core)
**Requirements**: REQ-390 – REQ-394

---

## 1. Overview

Add `kryten-llm memory compact` to the existing CLI. Operators can run compaction manually
for a one-time cleanup, preview with `--dry-run` before enabling the background sweeper, or
target a single user with `--user`. This sortie makes compaction usable without any service
restart.

---

## 2. Scope and Non-Goals

**In scope**: `compact` subcommand under the `memory` subparser in `kryten_llm/__main__.py`;
`--user`, `--dry-run`, `--threshold`, `--config` flags; output summary.

**Non-goals**: Service wiring (Sortie 3). Config model (Sortie 3). Any UI beyond the CLI
summary line.

---

## 3. Requirements

- **REQ-390** — `kryten-llm memory compact` runs one full compaction sweep using loaded
  config (or defaults if no `compaction` block is present).
- **REQ-391** — `--user USER` restricts compaction to facts belonging to that username.
- **REQ-392** — `--dry-run` activates `CompactionSweeper(dry_run=True)`: no store writes;
  output prefixed `[dry-run]`.
- **REQ-393** — `--threshold FLOAT` overrides the `merge_threshold` for this run only.
- **REQ-394** — Exits with code 0 on success, 1 on error. Prints:
  - Success: `"Compacted N fact(s)."` or `"[dry-run] Would compact N fact(s)."`
  - Error: error message to stderr.

---

## 4. Design

The `memory` subparser already handles `forget` and `inspect` commands. Add `compact` to
the same group:

```python
# In kryten_llm/__main__.py — memory subparser group
parser_compact = memory_sub.add_parser("compact", help="Merge near-duplicate facts in store")
parser_compact.add_argument("--user", metavar="USER",
                            help="Restrict compaction to a single username")
parser_compact.add_argument("--dry-run", action="store_true",
                            help="Preview without writing (REQ-392)")
parser_compact.add_argument("--threshold", type=float, metavar="FLOAT",
                            help="Override merge similarity threshold (REQ-393)")
parser_compact.set_defaults(func=_cmd_compact)
```

```python
async def _cmd_compact(args: argparse.Namespace, config: "LLMConfig") -> None:
    from kryten_llm.components.context.providers.long_term_memory import LongTermMemoryProvider
    from kryten_llm.components.memory.retention import CompactionSweeper

    ltm = _get_ltm_provider(config)   # existing helper that builds the provider
    if ltm is None:
        print("No long_term_memory provider configured.", file=sys.stderr)
        sys.exit(1)

    # Prefer CompactionConfig from config; fall back to defaults.
    ccfg = getattr(config, "compaction", None)
    threshold = args.threshold if args.threshold is not None else (
        ccfg.merge_threshold if ccfg else 0.85
    )
    min_facts = ccfg.min_facts_to_compact if ccfg else 10
    importance_cap = ccfg.importance_cap if ccfg else 10000

    sweeper = CompactionSweeper(
        store=ltm._store,
        embedder=ltm._embedder,
        merge_threshold=threshold,
        min_facts_to_compact=min_facts,
        importance_cap=importance_cap,
        dry_run=args.dry_run,
    )

    if args.user:
        records = await ltm._store.get_all(where={"user": args.user})
        n = await sweeper._sweep_user(args.user, records)
    else:
        n = await sweeper.sweep()

    prefix = "[dry-run] Would compact" if args.dry_run else "Compacted"
    print(f"{prefix} {n} fact(s).")
```

`_get_ltm_provider(config)` is a shared helper that builds (or reuses) a
`LongTermMemoryProvider` from the first enabled `long_term_memory` context provider config.
It should already exist for the `forget`/`inspect` commands; if not, add it in this sortie.

---

## 5. Implementation Plan

**Modify** `kryten_llm/__main__.py`:
- Add `compact` subparser to `memory` group.
- Add `_cmd_compact` async handler.
- Ensure `_get_ltm_provider` helper exists (add if needed).

---

## 6. Testing Strategy

Integration tests using an in-memory store seeded with near-duplicate facts:
- `compact` with no flags: `n > 0` on a seeded store.
- `--dry-run`: no store mutations; output starts with `[dry-run]`.
- `--user USER`: only the specified user's facts are processed.
- `--threshold 0.95`: stricter threshold → fewer merges.
- Missing `long_term_memory` provider in config: exits with code 1.

---

## 7. Acceptance Criteria

- [ ] `kryten-llm memory compact` runs without error on a seeded store.
- [ ] `--dry-run` produces no store writes; output is `[dry-run] Would compact N fact(s).`
- [ ] `--user USER` restricts to that user.
- [ ] `--threshold 0.95` overrides threshold.
- [ ] Exit code 1 when no LTM provider is configured.

---

## 8. Rollout

CLI only. No service change.

---

## 9. Documentation

`CHANGELOG.md` entry. Update `kryten-llm memory --help` output.
