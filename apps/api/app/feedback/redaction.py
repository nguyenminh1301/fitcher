"""Mask personal data in values users typed before a proposal is stored (Phase 12, DECISIONS §10).

Emails, phone numbers and runs of six or more digits become ``[MASKED_EMAIL]``,
``[MASKED_PHONE]`` and ``[MASKED_NUMBER]``. Years and short numbers stay, so a
question keeps its meaning. In SQL only string literals are masked; a reviewer
replaces each mask with a valid non-personal value before approving.
"""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w@])\+?\(?\d[\d\s().-]{7,}\d(?![\w@])")
NUMBER = re.compile(r"(?<![\w\[])\d{6,}(?![\w\]])")
LITERAL = re.compile(r"'((?:[^']|'')*)'")
PHONE_DIGITS = 9


def _phone(match: re.Match) -> str:
    text = match.group(0)
    # A bare digit run is a number; a phone number is written with + or separators.
    if text.isdigit() or sum(char.isdigit() for char in text) < PHONE_DIGITS:
        return text
    return "[MASKED_PHONE]"


def redact(text: str | None) -> str:
    """``text`` with emails, phone numbers and long digit runs masked."""
    text = EMAIL.sub("[MASKED_EMAIL]", text or "")
    text = PHONE.sub(_phone, text)
    return NUMBER.sub("[MASKED_NUMBER]", text)


def redact_sql(sql: str | None) -> str:
    """``sql`` with personal data masked inside its string literals only."""
    return LITERAL.sub(lambda match: f"'{redact(match.group(1))}'", sql or "")


def redact_spec(spec: dict) -> dict:
    """A copy of a QuerySpec with its filter values masked."""
    filters = []
    for item in spec.get("filters") or []:
        item = dict(item)
        value = item.get("value")
        if isinstance(value, str):
            item["value"] = redact(value)
        elif isinstance(value, list):
            item["value"] = [redact(entry) if isinstance(entry, str) else entry for entry in value]
        filters.append(item)
    return {**spec, "filters": filters}
