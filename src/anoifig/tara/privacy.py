"""Best-effort contact minimisation, not a general personal-information detector."""

import re

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
_SEPARATOR = r"[ ()\t-]*"


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
    + r")(?!\w|[.,]\d|[ ()\t-]*\d)"
)
_INTERNATIONAL_NUMBER = re.compile(r"(?<![\w+])\+[1-9](?:[ ()\t-]*\d){6,14}(?!\w|[.,]\d)")
_CURRENCY_BEFORE = re.compile(r"(?:[€£$]|\b(?:EUR|USD|GBP))\s*$", re.IGNORECASE)
_CURRENCY_AFTER = re.compile(r"^\s*(?:[€£$]|(?:EUR|USD|GBP)\b)", re.IGNORECASE)

CONTACT_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", re.IGNORECASE),
)


def minimise(text: str, *, contact_details: str | None = None) -> str:
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
