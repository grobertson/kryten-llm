# PRD (Draft): Memory-Quality Evaluation Harness

**Sprint**: 12 — `12-eval-harness`
**Status**: Drafted (N+2) — full PRD + rough sortie outline; sortie specs expanded before start
**Builds on**: Sprints 8–11 (memory features, quality, governance, engagement)
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

> **Detail level**: N+2 draft. The sortie outline below is intentionally rough; each becomes a
> full `SPEC-Sortie-{M}-{name}.md` (9-section template) when this sprint is promoted to "next".

---

## 1. Executive Summary

Sprints 8–11 introduced many tunable thresholds across memory recall, quality, and engagement.
Each was validated by ad hoc per-sortie fixtures; there is no standing way to measure memory
behavior *as a system*. This sprint builds an **offline evaluation harness**: curated fixture
corpora, scoring metrics (retrieval relevance, contradiction precision, disclosure safety), and
a report command that makes tuning data-driven and regressions detectable.

## 2. Problem Statement

- **What.** Similarity floors, boost weights, opposition thresholds, pooling strategies,
  engagement scores — all were tuned by intuition. A threshold that looked good during
  Sprint 8 may have drifted by Sprint 11.
- **Who.** Operators/maintainers (can't tune confidently), the community (quality drifts
  silently), and the project (disclosure-safety regressions could go undetected).
- **Why now.** Sprint 12 is the natural post-stabilization checkpoint — all major surfaces
  are in place, the fixture seeds already exist in the per-sortie tests, and the Sprint 11
  engagement score introduces a new tunable that needs a feedback loop.

## 3. Goals and Success Metrics

- A reproducible `pytest -m eval` target that scores memory behavior against curated fixtures
  and fails/warns when metrics fall below baselines.
- Fixture corpora for retrieval relevance, contradiction detection, and disclosure safety.
- A CLI `kryten-llm memory eval` command that prints a human-readable report.
- Success: retrieval precision@k, contradiction precision/recall, and disclosure-safety checks
  each have a defined baseline; the suite is re-runnable with no live services required.

## 4. User Stories

- *As a maintainer*, I want `pytest -m eval` to score retrieval relevance, so I can tell if a
  threshold change helps or hurts before committing.
- *As a maintainer*, I want contradiction-detection precision/recall tracked over time against
  a fixture set, so Sprint 9's embedding scorer and the heuristic fallback are measurable.
- *As a maintainer*, I want a disclosure-safety assertion that fails if a silenced user's fact
  surfaces, so privacy regressions are caught in CI.
- *As an operator*, I want a `kryten-llm memory eval` command that prints a quality report,
  so tuning is repeatable and shareable.

## 5. Technical Architecture (sketch)

- **Fixture format** (JSONL): each line is a scenario with `facts`, `query`, `expected_ids`,
  `silenced_users`, and optional `label`.
- **Harness**: instantiates a real `LongTermMemoryProvider` against an in-memory/Chroma store,
  seeds it with fixture facts, runs queries, and scores outputs.
- **Metrics**: precision@k (fraction of top-k results in `expected_ids`), MRR (mean reciprocal
  rank), contradiction precision/recall, disclosure-safety (0 silenced-user facts in output).
- **Integration**: `tests/eval/` directory, `@pytest.mark.eval` — excluded from the normal
  `pytest` run; wired into CI as a non-blocking trend via a separate step.

## 6. Dependencies

- Sprints 8–11 merged. Existing per-sortie test fakes can be promoted to fixtures.
  `kryten-llm[memory]` or `[pgvector]` for the store backend.

## 7. Security and Privacy

- Fixtures are offline, curated/anonymized — no live user data; no PII.
- Fixture curation must not include real usernames or messages; any seed data from real logs
  must be anonymized (see `user-extraction/` for the anonymization precedent).
- Disclosure-safety fixture tests act as a privacy regression gate.

## 8. Rollout Plan

- Ship as a separate `pytest -m eval` target; not run in the normal CI suite initially.
- After baselines stabilize over 2–3 sprints, promote to a CI gate on PRs that touch the
  memory components.
- `kryten-llm memory eval` CLI command can be invoked locally or in a staging environment.

## 9. Future Enhancements

- A/B scoring across provider configurations. Time-series baseline tracking. Seeding from
  anonymized production traces (with consent/governance review).

## 10. Open Questions

- What baseline thresholds define "pass" for each metric, and who owns them?
- Should the harness gate CI immediately or start as a trend report?
- How to version fixtures as the fact schema evolves (Sprint 10 retention changes)?

---

## Rough sortie outline (to be expanded)

| # | Sortie (working title) | Gist | Rough REQ |
|---|------------------------|------|-----------|
| 1 | Fixture format + loader | JSONL corpus schema; seed + teardown helpers | 250–254 |
| 2 | Retrieval scorer | precision@k + MRR over provider scopes vs. expected | 255–259 |
| 3 | Contradiction scorer | precision/recall on labeled fixture pairs | 260–264 |
| 4 | Disclosure-safety harness | Assert no silenced-user facts surface | 265–269 |
| 5 | Eval CLI + CI integration | `kryten-llm memory eval` report + `@pytest.mark.eval` | 270–279 |

**Dependencies**: 1 (loader) before all; 2, 3, 4 independent after 1; 5 integrates all.
