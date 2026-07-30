# PRD (Ideation): Memory-Aware Model Routing

**Sprint**: 15 — `15-model-routing`
**Status**: Complete ✅ — implemented 2026-07-30 (Sorties 1–4, REQ-310–329)
**Builds on**: Sprints 8–14
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

---

## 1. Problem Statement

Every LLM call today uses the same provider priority order regardless of context richness,
memory signal strength, or cost sensitivity. A turn with zero memory context and a weak
trigger needs only a cheap model; a turn with 8 high-confidence memory fragments and a
complex mention query warrants a stronger one. Without routing, we either overspend on
simple turns or underinvest on complex ones.

**Who benefits**: operators (cost efficiency), the community (better replies on rich-context
turns), and the project (enables a wider range of deployed models including local small models).

## 2. User Stories

- *As an operator*, I want cheap turns to use a fast local or small model, so I reduce API
  costs without sacrificing quality on the turns that matter.
- *As an operator*, I want turns with rich associative memory to use a stronger model that
  can reason about the context, so memory investment pays off in reply quality.
- *As a maintainer*, I want model routing decisions to be observable (logged, metered), so I
  can see what's happening and tune the routing policy.
- *As an operator*, I want the routing logic to be configurable (thresholds, model map), so
  I control the cost/quality trade-off per deployment.

## 3. Feasibility / Technical Read

- **Routing signal**: a per-turn `ContextSignal` value (0–1) aggregated from: number of
  memory fragments emitted, total character budget used, average fragment confidence (Sprint 13),
  and trigger priority. High signal → stronger model; low signal → cheaper model.
- **LLMManager**: add `route(signal)` method that maps `signal` to a provider tier (a list
  of providers in priority order). The rest of the request/response path is unchanged.
- **Config**: a `routing` block with thresholds and tier→provider mappings. Defaults to
  current behavior (single tier).
- **Observability**: log the routed tier and signal value per turn; expose as a Prometheus
  counter.
- **Risk**: if the signal is wrong (e.g. high-importance fragments that fit in few tokens),
  routing misfires. Needs a "safe" override for high-priority triggers regardless of signal.

## 4. Rough Scope (candidate sorties)

1. `ContextSignal` computation (fragment count, budget fraction, confidence mean, trigger priority).
2. `LLMManager.route(signal)` — tier selection and config schema.
3. Routing observability (log + metric per tier).
4. Per-trigger routing override (some triggers always use a preferred tier).

## 5. Open Questions

- What is the correct aggregation function for `ContextSignal`?
- Should the routing be a hard switch (threshold) or a weighted probability?
- How to handle providers in multiple tiers (e.g. OpenAI in both cheap and strong tiers)?
- Requires Sprint 12 eval harness to measure quality impact of routing decisions.

**REQ reservation**: REQ-310+ (finalized at promotion).
