# PRD: Confidence Calibration & Decay Hardening

**Sprint**: 18 — `18-confidence-calibration`
**Status**: Complete ✅ — implemented 2026-07-30 (Sorties 1–3, REQ-370–384)
**Builds on**: Sprints 8–17
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

---

## 1. Problem Statement

Sprint 13 introduced confidence as a dimension — corroboration raises it, contradiction lowers
it, and the retrieval ranker can weight it. However, the calibration of the default step/decay
values (0.05 / 0.1) was chosen without empirical data, and the Sprint 12 eval harness only
measures retrieval quality against ground-truth IDs, not whether the confidence scores are well
calibrated to actual fact reliability. As the system matures, over- or under-confident facts
will cause visible quality issues (over-hedging reliable facts, or over-stating dubious ones).

**Who benefits**: operators (reliable, trustworthy bot outputs), the community (calibrated
hedging feels natural, not paranoid), and the project (confidence scores are used by model
routing — miscalibrated scores lead to suboptimal provider choices).

## 2. User Stories

- *As a maintainer*, I want a calibration metric that tells me if the bot's confidence scores
  are well-calibrated against observed accuracy, so I can tune decay/step parameters with data.
- *As an operator*, I want the decay to automatically slow down for high-importance facts to
  prevent a single bad contradiction from undermining well-established knowledge.
- *As a community member*, I want hedged phrasing to match my actual uncertainty — not hedging
  things the bot has heard many times.

## 3. Feasibility / Technical Read

- **Calibration metric**: measure `P(fact_correct | confidence ≥ threshold)` against a
  human-labeled validation set (or proxy: fact survival rate after `forget_user` events).
  Add to the Sprint 12 eval harness.
- **Importance-gated decay**: modify `_apply_confidence_decay` to scale decay by
  `1 / importance` — a fact corroborated many times is more resistant to a single contradiction.
- **Temporal decay**: optionally reduce confidence for old, un-seen facts even without
  contradiction (separate from the retention sweeper — it's a confidence nudge, not deletion).
- **Dependency**: Sprint 12 eval harness must be extended before calibration can be measured.

## 4. Rough Scope

1. Calibration metric in the eval harness (extends Sprint 12).
2. Importance-gated contradiction decay.
3. Temporal confidence drift (optional, separate sweep from retention).

## 5. Open Questions

- What proxy for "fact correctness" can we measure without human labels?
- Should temporal drift be a separate task or fold into the retention sweeper?
- How do model routing decisions (Sprint 15) interact with miscalibrated confidence?

**REQ reservation**: REQ-370+ (finalised at promotion).
