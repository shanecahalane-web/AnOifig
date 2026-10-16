"""Minimise stored context replay; current input still needs explicit extraction."""

import re

CONTACT_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\w)(?:\+\d[\d ()-]{7,}\d|0[18]\d[\d ()-]{6,}\d)(?!\w)"),
    re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", re.IGNORECASE),
)


def minimise(text: str, *, contact_details: str | None = None) -> str:
    if contact_details:
        text = text.replace(contact_details, "[contact details omitted]")
    for pattern in CONTACT_PATTERNS:
        text = pattern.sub("[contact details omitted]", text)
    return text
