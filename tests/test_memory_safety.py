"""Tests for the privacy / safety gate (Phase 7b — REQ-015, CON-001)."""

import pytest

from kryten_llm.components.memory.safety import is_safe_message, sanitize_evidence


class TestIsSafeMessage:
    """Unit tests for is_safe_message()."""

    # --- Safe messages (should return True) ---

    def test_plain_preference(self):
        assert is_safe_message("I really love kung fu movies") is True

    def test_plain_habit(self):
        assert is_safe_message("I usually watch movies on Friday nights") is True

    def test_very_short_empty(self):
        assert is_safe_message("") is False
        assert is_safe_message("  ") is False

    # --- Email ---

    def test_email_rejected(self):
        assert is_safe_message("my email is user@example.com") is False

    def test_email_partial_rejected(self):
        assert is_safe_message("contact me at foo.bar+tag@domain.org") is False

    # --- URL ---

    def test_url_https_rejected(self):
        assert is_safe_message("check out https://example.com/path") is False

    def test_url_http_rejected(self):
        assert is_safe_message("go to http://test.org") is False

    def test_url_www_rejected(self):
        assert is_safe_message("visit www.example.com") is False

    # --- Phone ---

    def test_phone_us_format_rejected(self):
        assert is_safe_message("call me at 555-867-5309") is False

    def test_phone_parentheses_rejected(self):
        assert is_safe_message("my number is (555) 123-4567") is False

    # --- Long digit strings ---

    def test_six_digits_rejected(self):
        assert is_safe_message("my pin is 123456") is False

    def test_credit_card_rejected(self):
        assert is_safe_message("number 1234567890123456") is False

    def test_five_digits_ok(self):
        # 5 consecutive digits should be fine
        assert is_safe_message("I live at 12345 somewhere") is True

    # --- Address keywords ---

    def test_street_rejected(self):
        assert is_safe_message("I live on Maple Street") is False

    def test_avenue_rejected(self):
        assert is_safe_message("3rd avenue is great") is False

    def test_apartment_rejected(self):
        assert is_safe_message("I have an apartment downtown") is False

    # --- Drug references (FIXED: prototype returned True, must now return False) ---

    def test_cocaine_rejected(self):
        assert is_safe_message("cocaine is bad") is False

    def test_heroin_rejected(self):
        assert is_safe_message("heroin addiction is sad") is False

    def test_meth_rejected(self):
        assert is_safe_message("meth ruins lives") is False

    def test_fentanyl_rejected(self):
        assert is_safe_message("fentanyl overdoses are increasing") is False

    def test_mdma_rejected(self):
        assert is_safe_message("I've heard about MDMA") is False

    # --- Explicit age (FIXED: prototype returned True, must now return False) ---

    def test_explicit_age_im_rejected(self):
        assert is_safe_message("I'm 16 years old") is False

    def test_explicit_age_i_am_rejected(self):
        assert is_safe_message("I am 12 years old") is False

    def test_explicit_age_aged_rejected(self):
        assert is_safe_message("I'm aged 14") is False

    def test_vague_age_ok(self):
        # No explicit age disclosure — should pass
        assert is_safe_message("I'm an adult who likes action movies") is True


class TestSanitizeEvidence:
    """Tests for sanitize_evidence()."""

    def test_truncation(self):
        result = sanitize_evidence("x" * 300, max_length=50)
        assert len(result) <= 55  # 50 chars + ellipsis

    def test_email_redacted(self):
        result = sanitize_evidence("email me at foo@bar.com please")
        assert "@" not in result or "email" not in result or "[email]" in result

    def test_phone_redacted(self):
        result = sanitize_evidence("call 555-123-4567 now")
        assert "[phone]" in result

    def test_no_change_clean(self):
        clean = "I enjoy martial arts films"
        assert sanitize_evidence(clean) == clean
