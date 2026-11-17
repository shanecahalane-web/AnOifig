"""Confirmation sensitivity and best-effort model context minimisation."""

import re

CONFIRMATION = re.compile(r"(APPLY|REJECT) ([0-9A-F]{32})")
OMITTED_CONFIRMATION = "[confirmation omitted]"
# A complete challenge is sensitive even when adjacent to other characters.
_CHALLENGE = re.compile(r"[0-9a-f]{32,}", re.IGNORECASE)
_COMMAND_SHAPE = re.compile(r"(?:APPLY|REJECT)\b(?:[\s:=_-]+\S+)?", re.IGNORECASE)
_CODE_ARGUMENT = re.compile(r"\b(?:APPLY|REJECT)\b[\s:=_-]+[a-z0-9_-]{24,}", re.IGNORECASE)
_GROUPED_CODE_ARGUMENT = re.compile(
    r"(?<![^\W_])(?:APPLY|REJECT)[\W_]+([0-9a-f]+(?:[\W_]+[0-9a-f]+)+)",
    re.IGNORECASE,
)
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _has_grouped_challenge(body: str) -> bool:
    # Require a confirmation verb followed by a challenge's worth of hex digits.
    # WhatsApp formatting can put whitespace or punctuation between the groups.
    return any(
        sum(char in _HEX_DIGITS for char in match[1]) >= 32
        for match in _GROUPED_CODE_ARGUMENT.finditer(body)
    )


def is_confirmation_shaped(body: str) -> bool:
    """Classify sensitive text independently of exact command validation."""
    return (
        body == OMITTED_CONFIRMATION
        or _CHALLENGE.search(body) is not None
        or _COMMAND_SHAPE.fullmatch(body.strip().strip("\"'“”‘’`").strip()) is not None
        or _CODE_ARGUMENT.search(body) is not None
        or _has_grouped_challenge(body)
    )


# Irish geographic numbering areas have different subscriber lengths. Matching
# those lengths avoids treating arbitrary totals, dates and short references as
# telephone numbers. International forms drop the domestic leading zero.
_IRISH_LENGTHS = {
    5: (
        "22",
        "24",
        "25",
        "26",
        "27",
        "28",
        "29",
        "402",
        "404",
        "47",
        "504",
        "505",
        "58",
        "62",
        "63",
        "67",
        "68",
        "69",
        "93",
        "95",
        "96",
        "97",
        "98",
        "99",
    ),
    6: ("45", "51", "61", "91"),
    7: (
        "1",
        "21",
        "23",
        "41",
        "42",
        "43",
        "44",
        "46",
        "49",
        "52",
        "53",
        "56",
        "57",
        "59",
        "64",
        "65",
        "66",
        "71",
        "74",
        "83",
        "85",
        "86",
        "87",
        "89",
        "90",
        "94",
    ),
}
# Pasted/formatted numbers commonly use non-breaking spaces to keep digit
# groups together. Keep separators horizontal so a match cannot span lines.
_SEPARATOR = r"[ ()\t\u00a0\u202f-]*"


def _spaced_digits(digits: str) -> str:
    return _SEPARATOR.join(digits)


_IRISH_NUMBER = re.compile(
    r"(?<![\w+])(?:"
    + "|".join(
        rf"(?:0|\+{_spaced_digits('353')}|{_spaced_digits('00353')})"
        rf"{_SEPARATOR}{_spaced_digits(prefix)}(?:{_SEPARATOR}\d){{{length}}}"
        for length, prefixes in _IRISH_LENGTHS.items()
        for prefix in prefixes
    )
    + rf")(?!\w|[.,]\d|{_SEPARATOR}\d)"
)
_INTERNATIONAL_NUMBER = re.compile(rf"(?<![\w+])\+[1-9](?:{_SEPARATOR}\d){{6,14}}(?!\w|[.,]\d)")
_CURRENCY_BEFORE = re.compile(r"(?:[€£$]|\b(?:EUR|USD|GBP))\s*$", re.IGNORECASE)
_CURRENCY_AFTER = re.compile(r"^\s*(?:[€£$]|(?:EUR|USD|GBP)\b)", re.IGNORECASE)

CONTACT_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", re.IGNORECASE),
)


def minimise(text: str, *, contact_details: str | None = None) -> str:
    if _has_grouped_challenge(text):
        return OMITTED_CONFIRMATION
    text = _CHALLENGE.sub(OMITTED_CONFIRMATION, text)
    if contact_details:
        text = text.replace(contact_details, "[contact details omitted]")
    for pattern in CONTACT_PATTERNS:
        text = pattern.sub("[contact details omitted]", text)
    for pattern in (_IRISH_NUMBER, _INTERNATIONAL_NUMBER):
        source = text

        def redact_phone(match: re.Match[str], source: str = source) -> str:
            if _CURRENCY_BEFORE.search(source[: match.start()]) or _CURRENCY_AFTER.match(
                source[match.end() :]
            ):
                return match.group()
            return "[contact details omitted]"

        text = pattern.sub(redact_phone, text)
    return text
