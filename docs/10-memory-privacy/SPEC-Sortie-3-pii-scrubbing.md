# SPEC-Sortie-3: PII / secret scrubbing hardening

**Sprint**: 10 — Memory Privacy & Governance
**PRD**: [PRD-memory-privacy.md](PRD-memory-privacy.md)
**Status**: Planned
**Estimate**: 3–5h
**Depends on**: `components/memory/safety.py` (`is_safe_message`)
**Requirements**: REQ-190 – REQ-199

---

## 1. Overview

The write-path PII gate (`is_safe_message`) blocks emails, URLs, phones, long digit runs,
address keywords, drug/age references. Harden it against additional secret/PII classes and
build a **labeled fixture corpus** so precision/recall are measurable and regressions are
caught. This is the corpus's first line of privacy defense.

## 2. Scope and Non-Goals

**In scope**: expand the ruleset (API keys/tokens, credit-card Luhn, IPs, handles/DMs,
geolocation phrases); a fixture suite scoring precision/recall; keep the boolean
`is_safe_message` contract.

**Non-goals**: ML-based PII detection; scrubbing already-stored facts (that's Sortie 2/forget);
changing the write pipeline's placement of the gate.

## 3. Requirements

- **REQ-190** — Add detectors for: token/secret patterns (`sk-...`, JWT-like, hex ≥ 32),
  credit-card numbers validated by Luhn, IPv4/IPv6, and explicit geolocation phrases.
- **REQ-191** — `is_safe_message` remains a pure boolean gate; additions are additive (never
  *reduce* what is blocked).
- **REQ-192** — A labeled fixture set (`tests/fixtures/pii_corpus.jsonl`) with safe/unsafe
  examples drives precision/recall assertions.
- **REQ-193** — Precision/recall meet configured thresholds on the fixture set; the test fails
  if they regress.
- **REQ-194** — False-positive guardrails: benign messages (movie years, scores, casual
  numbers) are not over-blocked beyond the documented baseline.
- **REQ-195** — Performance: the combined ruleset stays within the existing per-message budget
  (regex only; no network).

## 4. Design

Extend `safety.py` with additional compiled patterns and a Luhn check, composed into the
existing `checks` list. Add a fixture-driven test that computes precision/recall:

```python
_LUHN_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
def _luhn_ok(s): ...        # digit checksum
# token/JWT/hex, IPv4/IPv6, geo phrases → additional compiled patterns
```

Fixtures label each line `{"text": ..., "safe": bool}`; the test asserts
`precision >= P and recall >= R`.

## 5. Implementation Plan

**Modify**
- `components/memory/safety.py` — new patterns + Luhn helper; extend `is_safe_message`.

**New**
- `tests/fixtures/pii_corpus.jsonl` — labeled examples.
- `tests/test_pii_scrubbing.py` — precision/recall + per-class unit tests.

## 6. Testing Strategy

- Per-class: each new detector flags its class (token, card+Luhn, IP, geo).
- Luhn: valid card blocked; invalid 16-digit string not falsely blocked as a card (still may
  hit long-digits rule — assert intended behavior).
- Fixture precision/recall ≥ thresholds.
- Benign numbers (e.g. "released in 1978", "42-0 final") not over-blocked.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] New secret/PII classes are blocked; measured precision/recall meet thresholds.
- [ ] No regression in what was previously blocked.
- [ ] Benign-number false-positive rate within the documented baseline.

## 8. Rollout

- Ships enabled (it only tightens the write gate). Note the (small) increase in blocked
  messages in the changelog.

## 9. Documentation

- `docs/user-memory-explained.md`: what is never stored.
- `CHANGELOG.md` entry (privacy hardening).
