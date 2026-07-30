# SPEC-Sortie-4: Disclosure-safety harness

**Sprint**: 12 — Memory-Quality Evaluation Harness
**PRD**: [PRD-eval-harness.md](PRD-eval-harness.md)
**Status**: Planned
**Estimate**: 2–4h
**Depends on**: Sortie 1 (loader + seeded provider)
**Requirements**: REQ-265 – REQ-269

---

## 1. Overview

Build a **privacy regression gate** that asserts silenced users' facts never appear in
cross-user retrieval output. Scenarios in `disclosure.jsonl` include silenced users; the
harness drives `_filter_silenced` and `provide()` and checks that none of their fact IDs
appear in the returned fragments.

## 2. Scope and Non-Goals

**In scope**: `disclosure.jsonl`; a harness that seeds the provider with facts for both
normal and silenced users, runs retrieval, asserts zero disclosure.

**Non-goals**: measuring retrieval quality (Sortie 2); testing the ModerationGate wire
(that's the unit tests in `test_moderation_gate.py`).

## 3. Requirements

- **REQ-265** — Each scenario has: `{"facts_silenced": [...], "facts_normal": [...],
  "silenced_users": [str], "query": str}`.
- **REQ-266** — The harness configures the provider's moderation gate with the
  `silenced_users` list (via a mock gate that returns the set deterministically).
- **REQ-267** — After `provide()`, assert no fact belonging to a silenced user appears in the
  returned fragments (neither by ID nor by content substring).
- **REQ-268** — At least 5 disclosure scenarios, including fail-closed gate (gate returns
  None) and empty silenced-user list (no filtering).
- **REQ-269** — Suite fails hard (`assert`) on any disclosure — this is a privacy gate.

## 4. Design

```python
class StaticModerationGate:
    def __init__(self, silenced: set[str]):
        self._silenced = silenced
    async def silenced_users(self): return frozenset(self._silenced)

def run_disclosure_scenario(scenario, provider):
    provider._mod_gate = StaticModerationGate(set(scenario.silenced_users))
    fragments = asyncio.run(provider.provide(req))
    for frag in fragments:
        for user in scenario.silenced_users:
            assert user not in frag.text, f"Disclosure: {user}'s fact in output"
```

## 5. Implementation Plan

**New**
- `tests/eval/test_disclosure.py` — `@pytest.mark.eval` tests.
- `tests/eval/fixtures/disclosure.jsonl` — ≥ 5 scenarios.
- `StaticModerationGate` (inline in the test or in `harness.py`).

## 6. Testing Strategy

- At least one scenario where a silenced user's fact *would* be top result without
  filtering — to verify the gate actually runs.
- Fail-closed scenario: gate returns None, verify no cross-user fragment emitted.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Zero silenced-user disclosures across all scenarios; test fails hard on any.
- [ ] Fail-closed scenario covered.
- [ ] At least 5 scenarios.

## 8. Rollout

- No production code changes.

## 9. Documentation

- `docs/EVAL_GUIDE.md`: disclosure scenario format; privacy regression gate description.
- `CHANGELOG.md` entry.
