# SPEC-Sortie-4: Category-routed fragments

**Sprint**: 8 — Associative Memory
**PRD**: [PRD-associative-memory.md](PRD-associative-memory.md)
**Status**: Planned
**Estimate**: 3–4h
**Depends on**: none (speaker-scoped; no cross-user disclosure)
**Requirements**: REQ-080 – REQ-089

---

## 1. Overview

Stored facts already carry a `category` in metadata. Instead of one flat bullet list, present
the speaker's facts as **labeled sections** (Preferences, Skills, History, …), each
independently sized and prioritized. This helps the model weight durable identity differently
from incidental history and lets operators trim low-value categories under budget pressure.

## 2. Scope and Non-Goals

**In scope**: group speaker facts by `category`; `sections` and `fragments` render modes;
per-category top-k and priority; generic bucket for unknown categories.

**Non-goals**: new categories or taxonomy changes (Phase 7f owns those); cross-user facts.

## 3. Requirements

- **REQ-080** — Speaker facts grouped by `metadata.category`.
- **REQ-081** — `mode="sections"` emits one fragment with ordered, labeled sections.
- **REQ-082** — `mode="fragments"` emits one fragment per category with per-category priority.
- **REQ-083** — `per_category_top_k` caps each section; `default` covers unlisted categories.
- **REQ-084** — Unknown categories routed to a generic section, not dropped.
- **REQ-085** — Within-category ordering preserves the Phase 7f boost.
- **REQ-086** — Disabled → byte-identical to today's flat `user_memory` fragment.

## 4. Design

Retrieve the speaker's facts as today, then group by `metadata.category`.

- `mode="sections"` → one `user_memory` fragment with headed sections in `order`:
  ```
  Known about alice:
    Preferences: loves synthwave · hates jump-scares
    Skills: runs a Plex server
  ```
- `mode="fragments"` → `user_memory_preference`, `user_memory_skill`, … each with own
  `priority`, so the budget trimmer can drop `history` before `preference`.
- `per_category_top_k` caps each section (`default` for unlisted). Unknown categories → generic
  section using `default` label/knobs. Within-category order keeps the Phase 7f boost.

## 5. Implementation Plan

**Modify**
- `long_term_memory.py` — grouping + two render modes; preserve boost order per group.
- `models/config.py` — `CategoryRoutingConfig`.
- `config.example.json` — `category_routing` block.

**Config**
```jsonc
"category_routing": {
  "enabled": false,
  "mode": "sections",
  "order": ["preference", "skill", "history", "self_description", "habit"],
  "labels": { "preference": "Preferences", "skill": "Skills", "history": "History",
              "self_description": "About them", "habit": "Habits" },
  "per_category_top_k": { "default": 2, "preference": 3 },
  "priority": { "preference": 42, "skill": 40, "history": 36, "default": 34 }
}
```

## 6. Testing Strategy

- Speaker with 3 categories → 3 ordered, correctly-labeled sections.
- `per_category_top_k` respected (preference 3, others 2).
- `mode="fragments"` yields independently-trimmable fragments; low-priority `history` dropped
  first under tight budget.
- Unknown category `"misc"` appears under default label.
- Disabled → golden flat fragment.
- Coverage ≥ 85%.

## 7. Acceptance Criteria

- [ ] Operators can down-weight/drop a category via config, no code change.
- [ ] Default (disabled) output unchanged.

## 8. Rollout

- Default-off. No cross-user exposure; no Sortie 0 dependency.
- Enable per channel; safe to combine with Sorties 1–3.

## 9. Documentation

- `config.example.json` comments.
- `docs/user-memory-explained.md`: category routing + modes.
- `CHANGELOG.md` entry.
