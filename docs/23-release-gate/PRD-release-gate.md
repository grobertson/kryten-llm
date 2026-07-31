# PRD: Release Gate

**Sprint**: 23 — `23-release-gate`
**Status**: ✅ Complete — gate clean (black/ruff/mypy/pytest), `v0.10.0` tagged
**Builds on**: Sprint 22 (release prep / gap removal)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)
**REQs**: REQ-481 – REQ-490

---

## 1. Executive Summary

Sprint 22 declared `v0.10.0` "shipped" (commit `chore: release v0.10.0`, ROADMAP marked
complete, CHANGELOG dated `2026-07-31`). A post-release audit of the working tree shows the
release-gate step (Sprint 22, Sortie 4 / REQ-478 & REQ-480) was **not actually executed
clean**: the toolchain reports formatting, lint, and type errors on Sprint 18–22 code, and
the `v0.10.0` git tag was never cut. The functional work of Sprints 18–22 is correct and
fully tested (941 passing tests), but the release is not gated. Sprint 23 fixes the
static-analysis defects, corrects one stale CHANGELOG note, re-runs the full gate to zero
errors, and cuts the annotated `v0.10.0` tag so the release is real.

This is a **hygiene sprint**. No feature behaviour changes. No config-schema, event,
command, or KV-contract changes. All fixes are internal (annotations, imports, formatting,
docs) and touch no public contract.

---

## 2. Problem Statement

### 2.1 `black --check .` fails — 7 files unformatted

The following Sprint 18–22 files are committed in a non-black-conformant state:

- `kryten_llm/__main__.py`
- `kryten_llm/models/config.py`
- `kryten_llm/components/prompt_builder.py`
- `kryten_llm/components/metrics_server.py`
- `kryten_llm/components/memory/log_date_utils.py`
- `kryten_llm/components/memory/retention.py`
- `kryten_llm/components/context/providers/long_term_memory.py`

`uv run black .` would reformat all seven. REQ-478 (step 1) is not satisfied at HEAD.

### 2.2 `ruff check .` fails — F821 undefined name `date`

`kryten_llm/__main__.py:167` declares `_parse_log_file(path, *, log_end_date: "date | None"
= None)`. The name `date` is imported **only locally** inside the function body
(`from datetime import date as _date`), so the module-scope string annotation `"date | None"`
references an undefined name. Ruff flags `F821`. This was introduced in Sprint 20.5
(`log_end_date` parameter). REQ-478 (step 2) is not satisfied at HEAD.

### 2.3 `mypy kryten_llm` fails — 2 errors

- `kryten_llm/__main__.py:167` — `Name "date" is not defined` (same root cause as §2.2).
- `kryten_llm/__main__.py:177` — `messages = []` needs a type annotation under mypy strict
  (`Need type annotation for "messages"`).

REQ-478 (step 3) is not satisfied at HEAD.

### 2.4 The `v0.10.0` tag was never created

`git tag -l` shows the highest release tag is `v0.9.4`. The release commit
`chore: release v0.10.0` exists but is untagged. Downstream consumers (api-gate, webqueue)
cannot pin to `v0.10.0`. REQ-480 is not satisfied.

### 2.5 Stale CHANGELOG note — `drives_participation`

The `[0.10.0]` block (Sprint 21 Config bullet) reads: "`drives_participation` flag stored
(default false — **see rework note**)." Sprint 22, Sortie 3 actually wired
`drives_participation` end-to-end. The "see rework note" caveat is now false and misleading
in a shipped changelog entry.

---

## 3. Goals and Success Metrics

| Metric | Target |
|--------|--------|
| `uv run black --check .` exits 0 | Pass |
| `uv run ruff check .` reports 0 errors | Pass |
| `uv run mypy kryten_llm` reports 0 errors | Pass |
| `uv run pytest` full suite passes (no regressions) | Pass |
| `__main__.py` `_parse_log_file` annotation resolves `date` at module scope | Pass |
| `messages` local in `_parse_log_file` is annotated | Pass |
| CHANGELOG `[0.10.0]` no longer references a "rework note" for `drives_participation` | Pass |
| Annotated git tag `v0.10.0` exists on the release commit | Pass |

---

## 4. User Stories

- *As a maintainer*, I want the committed tree to pass black/ruff/mypy so CI is green and the
  next contributor doesn't inherit a dirty baseline.
- *As a downstream consumer (api-gate/webqueue)*, I want a real `v0.10.0` tag so I can pin a
  stable, released version.
- *As an operator reading the CHANGELOG*, I want the `drives_participation` entry to describe
  the shipped behaviour accurately, without a dangling "rework note" caveat.

---

## 5. Technical Architecture

### 5.1 `__main__.py` static-analysis fixes (Sortie 1)

Root cause is a single missing module-scope import plus one missing annotation.

- Add `date` to the module-level datetime import so the string annotation resolves:
  ```python
  from datetime import date
  ```
  Then change the signature to a real (non-string) annotation and drop the redundant local
  alias where it duplicates the module import:
  ```python
  def _parse_log_file(path: Path, *, log_end_date: date | None = None) -> list[dict]:
  ```
- Annotate the accumulator:
  ```python
  messages: list[dict] = []
  ```

These are the only lines that must change to clear ruff F821 and both mypy errors.

### 5.2 Formatting (Sortie 1)

Run `uv run black .` once. It reformats the seven files in §2.1 with no semantic change.
No manual edits — black owns the layout.

### 5.3 CHANGELOG correction (Sortie 2)

In the `[0.10.0]` block, Sprint 21 Config bullet, replace:

> `drives_participation` flag stored (default false — see rework note).

with an accurate description, e.g.:

> `drives_participation` flag (default false); wired end-to-end in Sprint 22 so a strong
> proactive match on an auto-participation turn can override the eagerness gate.

### 5.4 Release gate + tag (Sortie 2)

Run the four toolchain commands to zero errors, commit the hygiene fixes
(`fix:`/`chore:` prefix), and cut the annotated tag:

```powershell
uv run black .
uv run ruff check --fix .
uv run mypy kryten_llm
uv run pytest
git tag -a v0.10.0 -m "Release v0.10.0"
```

---

## 6. Dependencies

- Sprint 22 must be merged (it is — the Sprint 22 release-prep commits are on `main`). No
  new external library dependencies.
- No cross-service impact until the tag is cut; then api-gate / webqueue may bump their
  `kryten-llm` pin (out of scope for this sprint).

---

## 7. Security and Privacy

No new data surfaces. No config, contract, or data-handling changes. The `date` import and
`messages` annotation are type-level only. No user-identifying data is touched.

---

## 8. Rollout Plan

Two additive, backward-compatible sorties. Sortie 1 makes the code changes and reformats;
Sortie 2 fixes docs, runs the gate clean, and tags. No config migration, no service restart
semantics, no downstream coordination required to land the fixes.

**Version decision**: `v0.10.0` was never tagged and (assumed) never published to PyPI, so
these hygiene fixes ship *under* the existing `0.10.0` version rather than forcing a
`0.10.1`. `pyproject.toml` stays at `0.10.0`; the CHANGELOG `[0.10.0]` block is corrected in
place (not re-dated). If `0.10.0` has already been published anywhere immutable, bump to
`0.10.1` instead and move these entries to a new block — confirm before tagging.

---

## 9. Future Enhancements

- Add a pre-commit hook (or CI job) running `black --check`, `ruff check`, and `mypy` so a
  non-conformant tree can never reach `main` again — the class of defect this sprint cleans up.

---

## 10. Open Questions

- **Q1**: Has `0.10.0` been published to PyPI or any immutable artefact store? If yes, the
  in-place CHANGELOG correction and re-use of the `0.10.0` version are not acceptable — bump
  to `0.10.1`. Default assumption (no tag exists → not published): correct in place and tag
  `0.10.0`.
