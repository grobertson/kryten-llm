# SPEC-Sortie-1: Static-Analysis & Formatting Fixes

**Sprint**: 23 — Release Gate
**PRD**: [PRD-release-gate.md](PRD-release-gate.md)
**Status**: ✅ Complete
**Estimate**: 30min
**Depends on**: Sprint 22 merged
**Requirements**: REQ-481 – REQ-485

---

## 1. Overview

Clear every black, ruff, and mypy error on the Sprint 18–22 code so the toolchain gate can
pass. The lint/type errors are localised to `kryten_llm/__main__.py`; the formatting drift
spans seven files and is resolved by a single `black` run.

---

## 2. Scope and Non-Goals

**In scope**: `__main__.py` `date` import + annotation fix; `messages` annotation;
`uv run black .` reformat of the seven drifted files.

**Non-goals**: CHANGELOG correction (Sortie 2). Tagging / release (Sortie 2). No behaviour
changes, no new tests beyond confirming the existing suite still passes.

---

## 3. Requirements

- **REQ-481** — `kryten_llm/__main__.py` imports `date` at module scope
  (`from datetime import date`) so the `_parse_log_file` annotation resolves. Ruff `F821`
  for line 167 is cleared.
- **REQ-482** — `_parse_log_file`'s signature uses a real annotation
  `log_end_date: date | None = None` (not the string form `"date | None"`). Any now-redundant
  local `from datetime import date as _date` alias inside the function is reconciled (keep a
  single, consistent reference to `date`).
- **REQ-483** — The `messages` accumulator in `_parse_log_file` is annotated
  `messages: list[dict] = []`. Mypy `var-annotated` for line 177 is cleared.
- **REQ-484** — `uv run black .` is run once; the seven drifted files are reformatted with
  no semantic change:
  `__main__.py`, `models/config.py`, `components/prompt_builder.py`,
  `components/metrics_server.py`, `components/memory/log_date_utils.py`,
  `components/memory/retention.py`,
  `components/context/providers/long_term_memory.py`.
- **REQ-485** — After the changes: `uv run ruff check .` reports 0 errors,
  `uv run mypy kryten_llm` reports 0 errors, `uv run black --check .` exits 0, and
  `uv run pytest` passes with no new failures or regressions.

---

## 4. Design

### `kryten_llm/__main__.py`

Top-level imports — add `date`:

```python
from datetime import date
from pathlib import Path
```

Function signature (line ~167) — real annotation:

```python
def _parse_log_file(path: Path, *, log_end_date: date | None = None) -> list[dict]:
```

Remove the local `from datetime import date as _date` alias inside the function body and use
the module-level `date` directly (or keep a single local import and drop the module-level one
— pick one and be consistent; the PRD prefers the module-level import so the annotation
resolves without `from __future__ import annotations`).

Accumulator (line ~177):

```python
messages: list[dict] = []
```

### Formatting

```powershell
uv run black .
```

Do not hand-edit layout; black owns it.

---

## 5. Verification

```powershell
uv run black --check .        # exits 0
uv run ruff check .           # 0 errors
uv run mypy kryten_llm        # 0 errors
uv run pytest -q              # all pass, no regressions
```

---

## 6. Notes

- These are the exact defects surfaced by the release audit; no other lint/type errors exist
  in the tree at HEAD.
- If a fresh black run touches files beyond the seven listed, inspect the diff — it should be
  pure whitespace/line-wrapping. Anything else is out of scope for this sortie.
