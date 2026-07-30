# PRD (Ideation): Cross-Channel Shared Knowledge

**Sprint**: 17 — `17-cross-channel`
**Status**: Next (N+1) — ideation PRD; full 10-section PRD + sortie specs written at promotion to Current
**Builds on**: Sprints 8–15 (memory surfaces, quality, governance, engagement, eval,
  confidence, model routing) — S16 dropped, no dependency on it
**Workflow**: [../../../AGENT-WORKFLOW-GUIDE.md](../../../AGENT-WORKFLOW-GUIDE.md)

> **Detail level**: N+1 ideation. A full PRD (10 sections) and sortie specs are written when
> promoted to Current. Drawn from strategic backlog theme A (cross-channel shared knowledge).

---

## 1. Problem Statement

Each bot instance is siloed: a fact learned in channel A is invisible to the bot in channel
B, even when sharing the same operator infrastructure. Community members who participate in
multiple channels must re-establish themselves from scratch in each. Meanwhile, the privacy
risk of accidental cross-channel disclosure must be zero — a channel's community data cannot
bleed into another channel without explicit consent.

**Who benefits**: operators running multi-channel deployments (shared knowledge reduces
redundant learning), returning community members (recognised across channels they've opted
into), and the project (completes the memory governance story).

## 2. User Stories

- *As an operator*, I want facts learned in my general channel to be available in my movie
  channel (when I configure it), so the bot feels coherent across channels.
- *As a community member*, I want to opt into cross-channel memory so the bot remembers me
  regardless of which channel I join.
- *As an operator*, I want a per-channel whitelist of "trusted partner channels" so I
  control which channels can share memory with which.
- *As a community member who has opted out*, I want my facts to remain strictly per-channel
  so cross-channel data sharing is opt-in only.

## 3. Feasibility / Technical Read

- **Store partitioning**: today, facts are keyed by user+summary within one collection/table.
  Cross-channel sharing requires either a shared store (per deployment) or a federation model
  where each channel's store reads from partner stores read-only.
- **Privacy boundaries**: the ModerationGate (Sprint 8) already filters silenced users per
  channel. Cross-channel must add a "channel consent" gate — a user's facts from channel A
  are only available in channel B if both the channel operator and the user have consented.
- **Sprint 10 governance**: the `forget.user` command must cascade across all channels in the
  shared deployment when cross-channel is enabled (right-to-erasure completeness).
- **Sprint 12 disclosure harness**: the privacy regression gate must be extended to cover
  cross-channel scenarios before this feature ships.
- **Risk**: highest privacy risk of all themes — design must be reviewed against the project's
  erasure guarantees (Sprint 10 forget.user) before implementation. GDPR compliance is not a
  requirement, but right-to-erasure completeness across channels is still a correctness concern.

## 4. Rough Scope (candidate sorties)

1. Per-deployment shared store partition (opt-in) + channel-consent config.
2. Cross-channel ModerationGate (check both channels' silenced lists).
3. User opt-in/opt-out mechanism (via chat command or operator command).
4. `forget.user` cascade across consented channels.
5. Sprint 12 disclosure harness extension for cross-channel scenarios.

## 5. Open Questions

- Shared store vs. federated read-only access to partner stores?
- How is user consent tracked — a new KV bucket or metadata on facts?
- Does `forget.user` require explicit cross-channel scope, or cascade automatically?
- Does cross-channel sharing require explicit user consent, or is operator-level config sufficient?

**REQ reservation**: REQ-340+ (finalised at promotion).
