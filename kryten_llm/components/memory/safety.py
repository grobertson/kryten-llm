"""Privacy / safety gate for long-term memory writes.

Phase 7b: CON-001 — messages containing PII must NOT be stored as facts.

Salvaged from ``user-extraction/factfinder.py`` with the prototype bug fixed:
the drug/explicit-age branches previously returned ``True`` (kept).  They now
return ``False`` (excluded) as required by Section 6 of the spec.

Sprint 10, Sortie 3 (REQ-190–195): Hardened with additional detectors for
API tokens/secrets, credit-card numbers (Luhn-validated), IPv4/IPv6 addresses,
and explicit geolocation phrases.  A labeled fixture corpus and precision/recall
tests in ``tests/test_pii_scrubbing.py`` measure and enforce detector quality.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Compiled PII / unsafe-content patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_PHONE_RE = re.compile(
    r"""
    (?:
        \+?1[-.\s]?              # optional country code
    )?
    (?:\(\d{3}\)|\d{3})          # area code
    [-.\s]?
    \d{3}[-.\s]?\d{4}            # number
    """,
    re.VERBOSE,
)
# 6+ consecutive digits (card numbers, SSNs, long PINs, etc.)
_LONG_DIGITS_RE = re.compile(r"\b\d{6,}\b")

# Address-like keywords
_ADDRESS_KW_RE = re.compile(
    r"\b(?:street|avenue|ave\.|blvd|boulevard|road|rd\.|drive|dr\.|"
    r"lane|ln\.|court|ct\.|highway|hwy|apt\.?|apartment|suite)\b",
    re.IGNORECASE,
)

# Drug references — exclusionary (FIX: prototype returned True; we return False)
_DRUG_RE = re.compile(
    r"\b(?:cocaine|heroin|meth(?:amphetamine)?|fentanyl|opioid|"
    r"crack|ketamine|mdma|ecstasy|lsd|mushrooms)\b",
    re.IGNORECASE,
)

# Explicit age references when combined with other sensitive context
_EXPLICIT_AGE_RE = re.compile(
    r"\b(?:i(?:'m|am)\s+\d{1,2}|age[d]?\s+\d{1,2}|\d{1,2}\s+years?\s+old)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Sprint 10, Sortie 3 — Extended PII detectors (REQ-190)
# ---------------------------------------------------------------------------

# API / secret tokens: OpenAI `sk-...`, Anthropic `sk-ant-...`, GitHub `ghp_/gho_/ghs_/ghr_`,
# and generic `Bearer <token>` / `token=<value>` in URLs or headers.
_TOKEN_PREFIX_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|"
    r"ghs_[A-Za-z0-9]{20,}|ghr_[A-Za-z0-9]{20,})\b",
    re.IGNORECASE,
)

# Long hex strings (≥ 32 hex chars) — often API keys, session tokens, hashes.
_HEX_SECRET_RE = re.compile(r"\b[0-9A-Fa-f]{32,}\b")

# JWT-like: three base64url segments separated by dots.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")

# Credit-card candidate: 13–19 digits, optionally space/dash separated.
# We use Luhn validation in ``_luhn_ok`` to reduce false positives (REQ-194).
_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ \-]?){12,18}\d\b")

# IPv4 address.
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)

# IPv6 address (full or compressed with `::` shorthand).
_IPV6_RE = re.compile(
    r"(?<![:\w])"  # negative lookbehind: not already in an addr
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"  # full
    r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:"  # trailing ::
    r"|:(?::[0-9A-Fa-f]{1,4}){1,7}"  # leading ::
    r"|(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}"  # one compression
    r"|::(?:[fF]{4}(?::0{1,4})?:)?(?:(?:25[0-5]|(?:2[0-4]|1\d|[1-9])?\d)\.){3}"
    r"(?:25[0-5]|(?:2[0-4]|1\d|[1-9])?\d)",  # IPv4-mapped
)

# Explicit geolocation phrases.
_GEO_KW_RE = re.compile(
    r"\b(?:"
    r"my\s+(?:address|location|coordinates?|gps)"
    r"|i(?:'m|\s+am)\s+(?:at|in|near)\s+\d"
    r"|zip\s*(?:code)?\s*[:\s]\s*\d{5}"
    r")"
    r"|(?:lat(?:itude)?|lon(?:g|gitude)?)\s*[:\s]\s*[-+]?\d",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _luhn_ok(s: str) -> bool:
    """Return True if the digit string *s* passes the Luhn checksum.

    Used to validate credit-card candidates and reduce false positives
    (REQ-194): a random sequence of digits rarely satisfies Luhn.
    """
    digits = [int(c) for c in s if c.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _has_luhn_card(text: str) -> bool:
    """Return True if *text* contains a credit-card-length digit sequence that
    passes Luhn validation (REQ-190, REQ-194)."""
    for m in _CARD_CANDIDATE_RE.finditer(text):
        digits_only = re.sub(r"[ \-]", "", m.group())
        if 13 <= len(digits_only) <= 19 and _luhn_ok(digits_only):
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_safe_message(text: str) -> bool:
    """Return ``True`` iff *text* is safe to store as a long-term memory fact.

    A message is considered UNSAFE (returns ``False``) if it contains any of:

    *Original detectors (Phase 7b)*
    * Email addresses
    * URLs / web links
    * Phone-number patterns
    * 6+ consecutive digits (card/ID numbers)
    * Physical address keywords
    * Drug references
    * Explicit age disclosures

    *New detectors (Sprint 10, Sortie 3, REQ-190)*
    * API key / secret tokens (OpenAI, GitHub prefixes)
    * Long hex strings (≥ 32 hex chars, likely tokens/hashes)
    * JWT-like blobs (three base64url segments)
    * Credit-card numbers passing Luhn validation
    * IPv4 and IPv6 addresses
    * Explicit geolocation phrases

    REQ-015 / CON-001 / REQ-191 (additions are strictly additive).
    """
    if not text or not text.strip():
        return False

    # Regex checks (fast path — short-circuit on first match).
    checks = [
        _EMAIL_RE,
        _URL_RE,
        _PHONE_RE,
        _LONG_DIGITS_RE,
        _ADDRESS_KW_RE,
        _DRUG_RE,
        _EXPLICIT_AGE_RE,
        # Sprint 10 additions
        _TOKEN_PREFIX_RE,
        _HEX_SECRET_RE,
        _JWT_RE,
        _IPV4_RE,
        _IPV6_RE,
        _GEO_KW_RE,
    ]
    for pattern in checks:
        if pattern.search(text):
            return False

    # Luhn credit-card check (separate because it's not a plain regex).
    if _has_luhn_card(text):
        return False

    return True


def sanitize_evidence(text: str, max_length: int = 200) -> str:
    """Return a truncated, redacted copy of *text* safe for the evidence field.

    Does NOT gate on PII — that is ``is_safe_message``'s job.  This merely
    truncates for storage efficiency and replaces obvious high-risk substrings
    in the stored evidence snippet.
    """
    # Truncate
    if len(text) > max_length:
        text = text[:max_length] + "…"

    # Coarse redaction of emails / phone numbers in the evidence field
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub("[phone]", text)
    return text
