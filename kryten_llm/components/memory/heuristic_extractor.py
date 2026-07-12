"""Heuristic fact extractor — salvaged logic from user-extraction/factfinder.py.

Phase 7b: REQ-031.

The logic is ported from the prototype, stream-processed per message (not
batched to top-25), with the following changes:
- Runs as an async method that returns ``list[Fact]``.
- Uses :func:`~kryten_llm.components.memory.safety.is_safe_message` as the
  privacy gate (no PII stored).
- Score threshold is driven by config (``write.min_message_score``), not hardcoded.
- No file I/O or DSU — those belong to the seed CLI.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from kryten_llm.components.memory.extractor import FACT_CATEGORIES, Fact
from kryten_llm.components.memory.safety import is_safe_message

# ---------------------------------------------------------------------------
# Patterns (salvaged from factfinder.py)
# ---------------------------------------------------------------------------

# First-person triggers
_FIRST_PERSON_RE = re.compile(
    r"\b(?:i(?:'m|'ve|'d|'ll|am|was|have|had|will|would|like|love|hate|"
    r"prefer|use|play|watch|listen|enjoy|do|did|can|could|"
    r"think|know|feel|want|need|work|live|go|went|used\s+to)|"
    r"\bi\b|"
    r"my|mine|myself)\b",
    re.IGNORECASE,
)

# Reactions / short acknowledgements to skip
_REACTION_RE = re.compile(
    r"^(?:lol|lmao|rofl|haha|heh|oh|ah|wow|wtf|omg|nice|cool|yeah|"
    r"yep|nope|yes|no|ok|okay|right|true|false|sure|thanks|ty|thx|"
    r"gg|rip|f+|based|cringe|kek)\s*[!?.]*\s*$",
    re.IGNORECASE,
)

# Category keyword sets
_PREF_KW_RE = re.compile(
    r"\b(?:like|love|prefer|enjoy|favorite|favourite|hate|dislike|" r"fan\s+of|into|obsessed)\b",
    re.IGNORECASE,
)
_HABIT_KW_RE = re.compile(
    r"\b(?:always|usually|often|sometimes|every\s+(?:day|week|morning|night)|"
    r"every\s+time|whenever|tend\s+to|used\s+to|regularly|daily|weekly)\b",
    re.IGNORECASE,
)
_PAST_KW_RE = re.compile(
    r"\b(?:used\s+to|back\s+when|years?\s+ago|once|formerly|previously|"
    r"grew\s+up|childhood|last\s+year|when\s+i\s+was)\b",
    re.IGNORECASE,
)
_LIFE_KW_RE = re.compile(
    r"\b(?:live|lives|living|born|from|grew?\s+up|moved|relocat|"
    r"work(?:s|ed|ing)?|job|career|school|college|university|degree)\b",
    re.IGNORECASE,
)
_SELF_DESC_RE = re.compile(
    r"\b(?:i(?:'m|\s+am)\s+(?:a|an|the)|i(?:'m|\s+am)\s+\w+)\b",
    re.IGNORECASE,
)

# Length bonuses for scoring
_INTERESTING_KW_RE = re.compile(
    r"\b(?:because|since|but|although|however|therefore|actually|"
    r"honestly|seriously|literally|basically)\b",
    re.IGNORECASE,
)

# Normalisation
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")

#: Maximum character length stored in a fact's evidence field.
MAX_EVIDENCE_LENGTH = 200


# ---------------------------------------------------------------------------
# Helper functions (salvaged / adapted)
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """Return a lowercase, punctuation-stripped, whitespace-normalised string."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def score_message(text: str) -> float:
    """Assign a quality score to a candidate message.

    Higher is better.  Driven by length, keyword bonuses, and first-person
    indicator density.  Returns a value in [0, 100].
    """
    if not text:
        return 0.0

    words = text.split()
    length = len(words)

    # Base score from word count (capped)
    base = min(length * 3.0, 45.0)

    # Bonus for interesting / connective words
    kw_count = len(_INTERESTING_KW_RE.findall(text))
    kw_bonus = min(kw_count * 5.0, 20.0)

    # Bonus for first-person indicators
    fp_count = len(_FIRST_PERSON_RE.findall(text))
    fp_bonus = min(fp_count * 3.0, 15.0)

    # Penalty for very short messages
    short_penalty = -20.0 if length < 4 else 0.0

    return max(0.0, min(base + kw_bonus + fp_bonus + short_penalty, 100.0))


def categorize(text: str) -> str:
    """Return the best-fit category for *text*.

    Falls back to ``"misc"`` when no category matches.
    """
    if _PREF_KW_RE.search(text):
        return "preference"
    if _HABIT_KW_RE.search(text):
        return "habit"
    if _PAST_KW_RE.search(text):
        return "past"
    if _LIFE_KW_RE.search(text):
        return "life_context"
    if _SELF_DESC_RE.search(text):
        return "self_description"
    return "misc"


def summarize_fact(username: str, text: str) -> str:
    """Produce a compact summary statement.

    Very simple paraphrase: strips filler prefixes and returns the rest with
    the user attributed.  An LLM extractor (Phase 7f) would do better here.
    """
    # Strip common filler prefixes
    text = re.sub(r"^(?:well[,\s]+|so[,\s]+|i\s+mean[,\s]+|like[,\s]+)", "", text, flags=re.I)
    text = text.strip()
    if not text:
        return ""
    # Ensure it ends with a period
    if text and text[-1] not in ".!?":
        text += "."
    return text


def stable_fact_id(user: str, summary: str) -> str:
    """Derive a stable ID for a fact (REQ-041 — idempotent seeding).

    Uses SHA-256 of ``user + normalised(summary)``.
    """
    key = f"{user}:{normalize(summary)}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def is_candidate(text: str) -> bool:
    """Return ``True`` if *text* is worth attempting to extract a fact from."""
    if not text or len(text.split()) < 3:
        return False
    if _REACTION_RE.match(text.strip()):
        return False
    if not _FIRST_PERSON_RE.search(text):
        return False
    return True


# ---------------------------------------------------------------------------
# HeuristicFactExtractor
# ---------------------------------------------------------------------------


class HeuristicFactExtractor:
    """Extracts facts using pattern-matching heuristics.

    REQ-031: Salvaged logic from ``user-extraction/factfinder.py``.
    REQ-033: Pure transform — no side-effects.

    Args:
        min_score: Minimum score for a message to produce a fact (default 25).
    """

    def __init__(self, min_score: float = 25.0):
        self._min_score = min_score

    async def extract(self, messages: list[dict[str, Any]], user: str) -> list[Fact]:
        """Extract candidate facts from *messages* attributed to *user*.

        Only processes messages sent *by* ``user``.  Applies the privacy gate
        before returning facts.
        """
        facts: list[Fact] = []
        seen_normalised: set[str] = set()

        for msg in messages:
            if msg.get("username", "").lower() != user.lower():
                continue

            text = msg.get("message", "").strip()
            if not text:
                continue

            # 1. Candidate filter (first-person / not a pure reaction)
            if not is_candidate(text):
                continue

            # 2. Privacy gate (CON-001)
            if not is_safe_message(text):
                continue

            # 3. Score
            msg_score = score_message(text)
            if msg_score < self._min_score:
                continue

            # 4. Summarise + categorise
            summary = summarize_fact(user, text)
            if not summary:
                continue

            # 5. Dedup by normalised summary
            norm_key = normalize(summary)
            if norm_key in seen_normalised:
                continue
            seen_normalised.add(norm_key)

            category = categorize(text)
            if category not in FACT_CATEGORIES:
                category = "misc"

            facts.append(
                Fact(
                    user=user,
                    category=category,
                    summary=summary,
                    evidence={"message": text[:MAX_EVIDENCE_LENGTH]},
                    score=msg_score,
                    source="live",
                )
            )

        return facts
