# SPEC-Sortie-2: CHANGELOG Correction, Gate, and `v0.10.0` Tag

**Sprint**: 23 — Release Gate
**PRD**: [PRD-release-gate.md](PRD-release-gate.md)
**Status**: ✅ Complete
**Estimate**: 20min
**Depends on**: Sortie 1 complete (tree passes black/ruff/mypy/pytest)
**Requirements**: REQ-486 – REQ-490

---

## 1. Overview

Correct the one stale CHANGELOG note, run the full toolchain gate to zero errors, commit the
Sprint 23 hygiene fixes, and cut the annotated `v0.10.0` tag that Sprint 22 never created.
This sortie makes the `v0.10.0` release real.

---

## 2. Scope and Non-Goals

**In scope**: CHANGELOG `[0.10.0]` `drives_participation` note fix; final gate run; hygiene
commit; annotated `v0.10.0` tag.

**Non-goals**: PyPI publish (manual, out of scope). `pyproject.toml` version change — it
already reads `0.10.0` and stays there (see PRD §8 / Open Question Q1). No code changes
(Sortie 1 carries all code).

---

## 3. Requirements

- **REQ-486** — In `CHANGELOG.md`, `[0.10.0]` block, Sprint 21 **Config** bullet: replace
  "`drives_participation` flag stored (default false — see rework note)." with an accurate
  description of the shipped behaviour, noting it was wired end-to-end in Sprint 22
  (e.g. "`drives_participation` flag (default false); wired end-to-end in Sprint 22 so a
  strong proactive match on an auto-participation turn can override the eagerness gate.").
- **REQ-487** — Confirm the `[0.10.0]` block otherwise matches the shipped feature set and
  the empty `[Unreleased]` header remains above it. Do **not** re-date `[0.10.0]` unless the
  release date genuinely changes.
- **REQ-488** — Full toolchain gate passes clean with zero errors on each command:
  1. `uv run black .`
  2. `uv run ruff check --fix .`
  3. `uv run mypy kryten_llm`
  4. `uv run pytest`
- **REQ-489** — Commit the Sprint 23 changes with a `fix:` (or `chore:`) prefix, e.g.
  `fix: clear black/ruff/mypy gate defects and correct CHANGELOG for v0.10.0 release`, body
  listing: the 3 static-analysis defects fixed, the 7 files reformatted, and the stale
  CHANGELOG note corrected.
- **REQ-490** — Create the annotated tag on the release commit:
  `git tag -a v0.10.0 -m "Release v0.10.0"`. Verify with `git tag -l "v0.10.0"` (non-empty)
  and `git describe --tags` on HEAD.

---

## 4. Toolchain Commands

Run in order from the repo root:

```powershell
uv run black .
uv run ruff check --fix .
uv run mypy kryten_llm
uv run pytest
```

All four must exit 0. Then:

```powershell
git add -A
git commit -m "fix: clear black/ruff/mypy gate defects and correct CHANGELOG for v0.10.0 release"
git tag -a v0.10.0 -m "Release v0.10.0"
git tag -l "v0.10.0"
```

---

## 5. Verification

- `uv run black --check .` exits 0; `ruff check .` and `mypy kryten_llm` report 0 errors;
  `pytest` passes.
- `git tag -l "v0.10.0"` prints `v0.10.0`.
- `CHANGELOG.md` `[0.10.0]` block contains no "see rework note" text.

---

## 6. Notes

- **Version guard (PRD Q1)**: if `0.10.0` has already been published to an immutable store,
  do **not** reuse it — bump `pyproject.toml` to `0.10.1`, move the corrected note into a new
  `[0.10.1]` block, and tag `v0.10.1` instead. Confirm before tagging.
- Do not push the tag or publish to PyPI as part of this sortie unless explicitly authorised
  — tag creation is local; publishing is a separate, confirmed step.
