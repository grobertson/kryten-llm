"""Privacy / safety gate for long-term memory writes.

Phase 7b: CON-001 — messages containing PII must NOT be stored as facts.

Salvaged from ``user-extraction/factfinder.py`` with the prototype bug fixed:
the drug/explicit-age branches previously returned ``True`` (kept).  They now
return ``False`` (excluded) as required by Section 6 of the spec.
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

# Drug references — exclusionary (FIX: prototype returned True here; we return False)
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
# Public API
# ---------------------------------------------------------------------------


def is_safe_message(text: str) -> bool:
    """Return ``True`` iff *text* is safe to store as a long-term memory fact.

    A message is considered UNSAFE (returns ``False``) if it contains:

    * Email addresses
    * URLs / web links
    * Phone-number patterns
    * 6+ consecutive digits (card/ID numbers)
    * Physical address keywords
    * Drug references  (**fix**: was ``True`` in prototype, now ``False``)
    * Explicit age disclosures  (**fix**: was ``True`` in prototype, now ``False``)

    REQ-015 / CON-001.
    """
    if not text or not text.strip():
        return False

    checks = [
        _EMAIL_RE,
        _URL_RE,
        _PHONE_RE,
        _LONG_DIGITS_RE,
        _ADDRESS_KW_RE,
        _DRUG_RE,
        _EXPLICIT_AGE_RE,
    ]
    for pattern in checks:
        if pattern.search(text):
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
