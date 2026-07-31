# SPEC-Sortie-4: Release Gate — v0.10.0

**Sprint**: 22 — Release Prep / Gap Removal
**PRD**: [PRD-release-prep.md](PRD-release-prep.md)
**Status**: Planned
**Estimate**: 30min
**Depends on**: Sorties 1–3 complete; all tests green
**Requirements**: REQ-476 – REQ-480

---

## 1. Overview

Finalise the release: version bump, CHANGELOG formalisation, and a clean
format/lint/type/test gate. This sortie produces the `v0.10.0` tag.

---

## 2. Scope and Non-Goals

**In scope**: `pyproject.toml` version bump; CHANGELOG `[Unreleased]` rename; new empty
`[Unreleased]` header; `uv run` toolchain gate; git tag.

**Non-goals**: PyPI publish (manual step, not automated here). Backlog
updates (separate docs commit). No code changes — Sorties 1–3 carry all code.

---

## 3. Requirements

- **REQ-476** — `pyproject.toml` `[project] version` changes from `"0.9.4"` to `"0.10.0"`.
  Version lives only here; no other files contain a version string that needs updating.
- **REQ-477** — `CHANGELOG.md`: rename `## [Unreleased]` to `## [0.10.0] - 2026-07-31`
  (or the actual release date). Insert a new empty `## [Unreleased]` section above it with
  placeholder `### Added` / `### Fixed` headings so future entries have a home.
- **REQ-478** — Toolchain gate passes clean with zero errors/warnings on each command:
  1. `uv run black .`
  2. `uv run ruff check --fix .`
  3. `uv run mypy kryten_llm`
  4. `uv run pytest` (full suite, including `test_compaction.py`, `test_proactive_injection.py`)
- **REQ-479** — Commit message: `chore: release v0.10.0` with a body listing the four
  sprints shipped (18–21) and the three gaps closed (Sprint 22 S1–S3).
- **REQ-480** — Git tag `v0.10.0` on the release commit (annotated tag preferred:
  `git tag -a v0.10.0 -m "Release v0.10.0"`).

---

## 4. Toolchain Commands

Run in order from the repo root:

```powershell
uv run black .
uv run ruff check --fix .
uv run mypy kryten_llm
uv run pytest
```

All four must exit 0. Fix any issues before tagging.

---

## 5. CHANGELOG Template After This Sortie

```markdown
## [Unreleased]

### Added

### Fixed

## [0.10.0] - 2026-07-31

### Added

- **Proactive Memory Injection** (Sprint 21 …
  …
```

---

## 6. Version Rationale

`0.9.4` → `0.10.0` (minor bump):

- Sprints 18–21 added four substantial feature areas with new config blocks, new CLI
  subcommands, new background tasks, and new context fragments.
- All changes are backward-compatible (default-off features, no contract breakage).
- The jump to `0.10.0` signals a meaningful capability milestone (end-to-end confidence
  calibration → compaction → temporal awareness → proactive injection chain).
