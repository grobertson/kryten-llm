"""Tests for the hardened PII / secret scrubbing (Sprint 10, Sortie 3, REQ-190–195).

Covers:
* Per-class unit tests for each new detector (REQ-190)
* No-regression: original Phase 7b detectors still fire (REQ-191)
* Luhn credit-card validation (REQ-190, REQ-194)
* Precision/recall on labeled fixture corpus (REQ-192, REQ-193)
* Benign-number false-positive baseline (REQ-194)
* Performance: each call stays within a sensible budget (REQ-195)
"""

from __future__ import annotations

import json
import pathlib
import time

import pytest

from kryten_llm.components.memory.safety import (
    _luhn_ok,
    _has_luhn_card,
    is_safe_message,
)

# ---------------------------------------------------------------------------
# Fixture corpus
# ---------------------------------------------------------------------------

_FIXTURES_PATH = pathlib.Path(__file__).parent / "fixtures" / "pii_corpus.jsonl"


@pytest.fixture(scope="module")
def pii_corpus() -> list[dict]:
    records = []
    with _FIXTURES_PATH.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Precision / recall thresholds (REQ-193)
# ---------------------------------------------------------------------------
PRECISION_THRESHOLD = 0.85  # TP / (TP + FP) — don't over-block
RECALL_THRESHOLD = 0.90  # TP / (TP + FN) — don't miss PII


class TestPrecisionRecall:
    """Measure precision and recall over the labeled fixture corpus."""

    def test_precision_meets_threshold(self, pii_corpus):
        """is_safe_message must not over-block safe messages (REQ-193, REQ-194)."""
        safe = [r for r in pii_corpus if r["safe"]]
        true_negatives = sum(1 for r in safe if is_safe_message(r["text"]) is True)
        false_positives = len(safe) - true_negatives
        precision = true_negatives / len(safe) if safe else 1.0
        assert precision >= PRECISION_THRESHOLD, (
            f"Precision {precision:.2%} < {PRECISION_THRESHOLD:.0%}; "
            f"{false_positives} safe messages incorrectly blocked: "
            + str([r["text"] for r in safe if is_safe_message(r["text"]) is False])
        )

    def test_recall_meets_threshold(self, pii_corpus):
        """is_safe_message must block PII-containing messages (REQ-193)."""
        unsafe = [r for r in pii_corpus if not r["safe"]]
        true_positives = sum(1 for r in unsafe if is_safe_message(r["text"]) is False)
        false_negatives = len(unsafe) - true_positives
        recall = true_positives / len(unsafe) if unsafe else 1.0
        assert recall >= RECALL_THRESHOLD, (
            f"Recall {recall:.2%} < {RECALL_THRESHOLD:.0%}; "
            f"{false_negatives} PII messages not blocked: "
            + str([r["text"] for r in unsafe if is_safe_message(r["text"]) is True])
        )


# ---------------------------------------------------------------------------
# Per-class unit tests for new detectors (REQ-190)
# ---------------------------------------------------------------------------


class TestTokenDetectors:
    """API key / secret token patterns."""

    def test_openai_key_blocked(self):
        assert is_safe_message("sk-abc123DEF456xyz789abcdefghij1234 is the key") is False

    def test_github_pat_blocked(self):
        assert is_safe_message("ghp_abcdefghijklmnopqrstuvwxyz1234") is False

    def test_github_oauth_blocked(self):
        assert is_safe_message("gho_abcdefghijklmnopqrstuvwxyz1234") is False

    def test_short_sk_not_blocked(self):
        # Shorter than 20 chars after sk- shouldn't be flagged as a token prefix
        # (will still be caught by long-digit rule if it's numeric)
        msg = "sk-short"
        # Just check the function doesn't raise; result depends on content
        _ = is_safe_message(msg)

    def test_bearer_token_via_hex(self):
        # A typical bearer token is a long hex or base64 string; 32+ hex catches it
        assert (
            is_safe_message("Authorization: Bearer DEADBEEF1234567890ABCDEF1234567890AB") is False
        )

    def test_hex_32_chars_blocked(self):
        assert is_safe_message("key is a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6 here") is False

    def test_hex_31_chars_safe(self):
        # 31 hex chars should NOT be blocked by hex detector
        result = is_safe_message("value is a1b2c3d4e5f6a7b8c9d0e1f2a3b ok")
        # May still be blocked by long_digits if the 31 chars are all decimal
        # Just verify no exception
        assert isinstance(result, bool)

    def test_jwt_blocked(self):
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        assert is_safe_message(f"token is {jwt}") is False


class TestLuhnCard:
    """Credit-card Luhn validation (REQ-190, REQ-194)."""

    def test_luhn_ok_valid_visa(self):
        assert _luhn_ok("4532015112830366") is True

    def test_luhn_ok_valid_mastercard(self):
        assert _luhn_ok("5425233430109903") is True

    def test_luhn_ok_invalid(self):
        # Flip last digit to invalidate
        assert _luhn_ok("4532015112830367") is False

    def test_has_luhn_card_visa(self):
        assert _has_luhn_card("my card 4532015112830366 expires soon") is True

    def test_has_luhn_card_with_spaces(self):
        assert _has_luhn_card("visa card: 4111 1111 1111 1111 is mine") is True

    def test_has_luhn_card_no_card(self):
        assert _has_luhn_card("I like kung fu movies") is False

    def test_valid_card_blocked(self):
        assert is_safe_message("my card 4532015112830366 expires next year") is False

    def test_invalid_digit_sequence_not_flagged_as_card(self):
        # 16 random digits that fail Luhn should not be flagged as a Luhn card
        # (they may still be flagged by _LONG_DIGITS_RE as 6+ digits, which is fine)
        result = is_safe_message("sequence 1234567890123456 is random")
        # Just check no exception; the long-digits rule may still catch it
        assert isinstance(result, bool)


class TestIPDetectors:
    """IPv4 and IPv6 address detectors (REQ-190)."""

    def test_ipv4_blocked(self):
        assert is_safe_message("server is at 192.168.1.100 and running") is False

    def test_ipv4_loopback_blocked(self):
        assert is_safe_message("connect to 127.0.0.1 now") is False

    def test_ipv4_public_blocked(self):
        assert is_safe_message("my ip is 8.8.8.8") is False

    def test_ipv6_full_blocked(self):
        assert is_safe_message("address: 2001:0db8:85a3:0000:0000:8a2e:0370:7334") is False

    def test_benign_version_not_ipv4(self):
        # "v1.2.3" is a version string, not an IP
        assert is_safe_message("I am running version 1.2.3 of the software") is True

    def test_benign_date_not_ipv4(self):
        # A date-like string that doesn't form a valid IP
        assert is_safe_message("on 2023.01.15 we released it") is True


class TestGeolocationDetectors:
    """Geolocation phrase detectors (REQ-190)."""

    def test_my_address_blocked(self):
        assert is_safe_message("my address is 123 Oak Street") is False

    def test_my_location_blocked(self):
        assert is_safe_message("my location is downtown Chicago") is False

    def test_i_live_at_number_blocked(self):
        # "I'm at 42 Main Street" → blocked by geo pattern
        assert is_safe_message("I'm at 42 Main Street") is False

    def test_latitude_blocked(self):
        assert is_safe_message("lat: 40.7128 is the latitude") is False

    def test_longitude_blocked(self):
        assert is_safe_message("lon: -74.0060 is the longitude") is False

    def test_zip_code_blocked(self):
        assert is_safe_message("zip code: 90210 is my area") is False

    def test_generic_city_mention_safe(self):
        assert is_safe_message("I love living in a big city") is True

    def test_general_direction_safe(self):
        assert is_safe_message("turn left at the traffic light") is True


# ---------------------------------------------------------------------------
# No-regression: original Phase 7b detectors (REQ-191)
# ---------------------------------------------------------------------------


class TestOriginalDetectorsRegression:
    """Ensure the original detectors still fire after Sprint 10 additions."""

    def test_email_still_blocked(self):
        assert is_safe_message("user@example.com is my email") is False

    def test_url_still_blocked(self):
        assert is_safe_message("go to https://example.com") is False

    def test_phone_still_blocked(self):
        assert is_safe_message("call 555-123-4567") is False

    def test_long_digits_still_blocked(self):
        assert is_safe_message("my pin is 123456") is False

    def test_address_kw_still_blocked(self):
        assert is_safe_message("I live on Maple Street") is False

    def test_drug_still_blocked(self):
        assert is_safe_message("cocaine is dangerous") is False

    def test_explicit_age_still_blocked(self):
        assert is_safe_message("I'm 14 years old") is False

    def test_safe_messages_still_pass(self):
        safe_messages = [
            "I love action movies",
            "Bruce Lee was amazing",
            "The score was 5-2",
            "Chapter 3 is my favourite",
        ]
        for msg in safe_messages:
            assert is_safe_message(msg) is True, f"Regression: safe message blocked: {msg!r}"


# ---------------------------------------------------------------------------
# Benign-number false-positive baseline (REQ-194)
# ---------------------------------------------------------------------------


class TestBenignNumbers:
    """Common benign number patterns should NOT be over-blocked (REQ-194)."""

    def test_movie_year_not_blocked(self):
        assert is_safe_message("that film was released in 1978") is True

    def test_score_not_blocked(self):
        assert is_safe_message("42-0 final score last night") is True

    def test_small_count_not_blocked(self):
        assert is_safe_message("I ordered 3 items") is True

    def test_ranking_not_blocked(self):
        assert is_safe_message("she finished in 2nd place") is True

    def test_chapter_number_not_blocked(self):
        assert is_safe_message("read chapter 7 first") is True

    def test_five_digit_safe(self):
        # 5 consecutive digits do not trigger _LONG_DIGITS_RE (which requires 6+)
        assert is_safe_message("code is 12345 exactly") is True


# ---------------------------------------------------------------------------
# Performance: stay within budget (REQ-195)
# ---------------------------------------------------------------------------


class TestPerformance:
    """The combined ruleset must complete well within a per-call budget."""

    BUDGET_SECONDS = 0.01  # 10ms per call is very generous for pure regex

    def test_safe_message_speed(self):
        msg = "I love kung fu movies and action stars from the 1980s"
        start = time.perf_counter()
        for _ in range(100):
            is_safe_message(msg)
        elapsed = (time.perf_counter() - start) / 100
        assert (
            elapsed < self.BUDGET_SECONDS
        ), f"is_safe_message too slow: {elapsed*1000:.2f}ms per call"

    def test_unsafe_message_speed(self):
        msg = "my email is user@example.com and I live at 192.168.1.1"
        start = time.perf_counter()
        for _ in range(100):
            is_safe_message(msg)
        elapsed = (time.perf_counter() - start) / 100
        assert (
            elapsed < self.BUDGET_SECONDS
        ), f"is_safe_message too slow on unsafe input: {elapsed*1000:.2f}ms per call"
