# PRD (Lite): Memory-Quality Evaluation Harness

**Sprint**: 12 — `12-eval-harness`
**Status**: Ideation (Future N+3) — problem statement + user stories + feasibility only
**Builds on**: Sprints 8–11 (memory features, quality, governance, engagement)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

> **Detail level**: N+3. Problem, user stories, and a feasibility read only. A full PRD (10
> sections) and sortie specs are written when this is promoted toward "next". Chosen from the
> strategic backlog (theme D) because it is privacy-neutral and de-risks tuning for every prior
> sprint. Remaining strategic themes live in [ROADMAP.md](ROADMAP.md).

---

## 1. Problem Statement

Sprints 8–11 introduced many tunable thresholds — similarity floors, boost weights,
contradiction opposition, pooling strategies, engagement scores — each validated only by ad
hoc per-sortie fixtures. There is **no standing way to measure memory quality** (retrieval
relevance, contradiction precision, disclosure safety) as a whole, so tuning is guesswork and
regressions can slip in. We need an **offline evaluation harness** that scores memory behavior
against curated fixtures and runs as a repeatable regression suite.

**Who benefits**: operators/maintainers (data-driven tuning, regression safety) and, indirectly,
the community (steadily better, safer recall). The harness is privacy-neutral (offline, curated
data).

## 2. User Stories

- *As a maintainer*, I want to score retrieval relevance against a fixed fixture set, so I can
  tell whether a threshold change helps or hurts.
- *As a maintainer*, I want contradiction-detection precision/recall tracked over time, so
  Sprint 9's upgrade and future changes are measurable.
- *As a maintainer*, I want a **disclosure-safety** check that fails if a silenced user's fact
  could surface, so privacy regressions are caught automatically.
- *As an operator*, I want a single command that reports memory-quality metrics, so tuning is
  repeatable and shareable.

## 3. Feasibility / Technical Read

- **Fixtures already exist in miniature**: each Sprint 8–9 sortie shipped focused test
  fixtures; the harness generalizes these into curated corpora (`facts`, `queries`,
  `expected`, `silenced`).
- **Reuses real components**: run the actual embedder + `VectorStore` (in-memory/Chroma) +
  `LongTermMemoryProvider` scopes against fixtures; score outputs — no production changes
  required.
- **Metrics**: retrieval relevance (precision@k / MRR vs. expected), contradiction
  precision/recall, disclosure-safety (assert no silenced/again-muted user surfaces).
- **Integration**: a CLI/pytest target that emits a metrics report; optionally wired into CI as
  a non-blocking trend, then a gate once baselines stabilize.
- **Risk**: fixture curation effort and keeping corpora representative; mitigate by seeding from
  anonymized real logs already used in `user-extraction`.
- **Privacy**: offline, curated/anonymized data only; no live disclosure surface.

## 4. Rough Scope (candidate sorties — not yet specced)

- Fixture corpus format + loader (`facts`/`queries`/`expected`/`silenced`).
- Retrieval-relevance scorer (precision@k, MRR) over provider scopes.
- Contradiction precision/recall scorer (reuses Sprint 9 Sortie 3 fixtures).
- Disclosure-safety assertion harness (shadow-mute / cross-user).
- Report command + optional CI trend/gate.

## 5. Open Questions

- What baseline thresholds define "pass" for each metric, and who owns them?
- Should the harness run in CI as a gate or a trend first? (Likely trend → gate.)
- How to source/refresh representative fixtures without storing PII?

**Rough REQ reservation**: 250–279 (finalized at promotion).
