# SPEC-Sortie-5: Eval CLI + CI integration

**Sprint**: 12 — Memory-Quality Evaluation Harness
**PRD**: [PRD-eval-harness.md](PRD-eval-harness.md)
**Status**: Planned
**Estimate**: 2–3h
**Depends on**: Sorties 1–4
**Requirements**: REQ-270 – REQ-279

---

## 1. Overview

Wire the four scorers into a human-readable CLI command (`kryten-llm memory eval`) and
formalize the `@pytest.mark.eval` target as a non-blocking CI step. After this sortie a
maintainer can run `kryten-llm memory eval` locally and get a concise report of all memory
quality metrics.

## 2. Scope and Non-Goals

**In scope**: `kryten-llm memory eval` CLI subcommand; a combined report; `@pytest.mark.eval`
wired to CI (non-blocking initially); summary printed to stdout.

**Non-goals**: time-series baseline storage; A/B comparison; automated PR gate (post-MVP).

## 3. Requirements

- **REQ-270** — `kryten-llm memory eval` subcommand runs all eval scenarios and prints a
  summary table: metric name, value, baseline, pass/fail.
- **REQ-271** — The CLI accepts `--fixture-dir` to override the default `tests/eval/fixtures`.
- **REQ-272** — Exit code 0 if all baselines pass; non-zero if any fail.
- **REQ-273** — CI (GitHub Actions / systemd test step) adds a `pytest -m eval` step that
  is non-blocking initially but records results.
- **REQ-274** — A `--json` flag emits the report as machine-readable JSON for trend tracking.
- **REQ-275** — Performance: the full eval suite completes in < 30 seconds using mocked
  embeddings.

## 4. Design

```
kryten-llm memory eval [--fixture-dir PATH] [--json]
```

Internally calls `FixtureLoader`, seeds a mock provider, runs
`score_retrievals / score_contradictions / run_disclosure_checks`, and
prints a Markdown table or JSON blob.

## 5. Implementation Plan

**Modify**
- `kryten_llm/__main__.py` — add `memory eval` subcommand.

**New**
- `kryten_llm/eval_runner.py` — `run_eval_suite(fixture_dir) -> EvalReport`.
- `.github/workflows/eval.yml` — (or append to existing CI) eval step.

## 6. Testing Strategy

- Unit test: `run_eval_suite` with all-passing mock data → exit 0.
- Unit test: one failing baseline → exit non-zero, correct metric named in output.
- CLI invocation test (subprocess) verifying stdout/exit code.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] `kryten-llm memory eval` runs and prints a summary table.
- [ ] Exit code reflects pass/fail status.
- [ ] `--json` flag works.
- [ ] CI step added (non-blocking).

## 8. Rollout

- Ships as a new CLI verb; existing `memory forget/stats` verbs unaffected.
- Enable as a blocking CI gate after two stable green runs.

## 9. Documentation

- `README.md`: mention `kryten-llm memory eval`.
- `docs/EVAL_GUIDE.md`: full eval workflow, adding scenarios, CI notes.
- `CHANGELOG.md` entry.
