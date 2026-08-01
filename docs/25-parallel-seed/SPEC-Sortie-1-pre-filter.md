# SPEC-Sortie-1: Pre-Batch Bot Filter

**Sprint**: 25 — Parallel Seed + Checkpoint/Resume
**PRD**: [PRD-parallel-seed.md](PRD-parallel-seed.md)
**Status**: Planned
**Estimate**: 1.5h
**Depends on**: Nothing
**Requirements**: REQ-497 – REQ-500

---

## 1. Overview

Filter messages from excluded users (bots) out of the message list *before* assembling
LLM extraction batches. Each batch of `batch_max_size` will contain only human messages,
maximising fact yield per LLM call.

Also corrects the `config.example.json` exclude list, which is missing `SaveTheRobots`
and `CynthiaRothbot`.

---

## 2. Requirements

- **REQ-497** — In `_seed_via_llm`, after parsing a file and before assembling batch
  starts, build:
  ```python
  human_messages = [m for m in messages if m["username"].lower() not in exclude]
  ```
  All batch assembly, offset tracking, and progress accounting use `human_messages`.
  The `exclude` set is unchanged (still `provider._observe_exclude`).

- **REQ-498** — The post-extraction exclude check (`if ef.target_user.lower() in exclude`)
  is retained as a safety net for facts attributed to bot names that appear in bot
  dialogue (e.g., the LLM extracting a self-referential bot fact). It is NOT removed.

- **REQ-499** — The progress summary line printed before processing each file reports
  both counts:
  ```
  Processing chat-messages.log — 312,450 human messages
      (229,245 bot messages filtered from 541,695 total)
  ```

- **REQ-500** — `config.example.json`: add `SaveTheRobots` and `CynthiaRothbot` to
  `observe_exclude_users` in the `write` block of the `long_term_memory` provider.

---

## 3. Implementation

### 3.1 `kryten_llm/__main__.py` — `_seed_via_llm`

#### Replace the per-file processing header

Old:
```python
    for log_path, messages in all_file_data:
        print(f"\nProcessing {log_path.name} — {len(messages):,} messages (LLM extractor)")

        file_facts = 0
        # Process newest batch first …
        batch_starts = list(range(0, len(messages), batch_size))
        for start in reversed(batch_starts):
            batch = messages[start : start + batch_size]
```

New:
```python
    for log_path, messages in all_file_data:
        # REQ-497: build from human messages only so every batch slot is productive.
        human_messages = [m for m in messages if m["username"].lower() not in exclude]
        bot_count = len(messages) - len(human_messages)
        print(
            f"\nProcessing {log_path.name} — {len(human_messages):,} human messages"
            + (f"\n    ({bot_count:,} bot messages filtered from {len(messages):,} total)" if bot_count else "")
        )

        file_facts = 0
        batch_starts = list(range(0, len(human_messages), batch_size))
        for start in reversed(batch_starts):
            batch = human_messages[start : start + batch_size]
```

#### Adjust total_messages calculation

The pre-parse summary computed before the main loop must also count only human messages:

```python
    total_messages = sum(
        len([m for m in msgs if m["username"].lower() not in exclude])
        for _, msgs in all_file_data
    )
```

### 3.2 `config.example.json`

Add the missing bot names to `observe_exclude_users`:
```json
"observe_exclude_users": [
  "ZcoinBank", "VHSOracle", "FaxyBrown", "Faxy",
  "SaveTheRobots", "CynthiaRothbot"
]
```

---

## 4. Tests (`tests/test_seed_pre_filter.py`)

- **REQ-497 test**: seed with a message list mixing human and excluded-user messages;
  assert the extractor receives only human messages.
- **REQ-498 test**: if the extractor returns a fact attributed to a bot name, assert it
  is not persisted (the post-extract safety net still fires).
- **REQ-499 test**: capture stdout; assert the filtered count appears in the print line
  when bot messages are present; assert no filter line when bot_count == 0.

---

## 5. Acceptance Checklist

- [ ] Extractor never receives a message from a user in `observe_exclude_users`
- [ ] Post-extraction safety net still rejects bot-attributed facts
- [ ] Progress total and batch counts reflect human-message counts
- [ ] `config.example.json` updated with missing bot names
- [ ] black / ruff / mypy / pytest all clean
