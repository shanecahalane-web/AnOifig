"""Conservative source-expression grammar for untrusted extraction proposals.

Offsets always refer to the complete user input. Evidence selects an expression;
it cannot remove its currency, polarity, precision, clause or alternatives.
Unsupported language is a clarification, never permission to guess a value.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class NumericToken:
    start: int
    end: int
    value: Decimal


@dataclass(frozen=True)
class Clause:
    start: int
    end: int
    text: str


def evidence_spans(message: str, evidence: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    offset = 0
    while (start := message.find(evidence, offset)) != -1:
        spans.append((start, start + len(evidence)))
        offset = start + 1
    return spans


def clauses(message: str) -> list[Clause]:
    """Keep item/field clauses distinct without splitting decimal/grouped digits."""
    boundaries = re.finditer(
        r"[;\n!?]|\.(?=\s|$)|,(?![0-9])|\b(?:and|but)\b|"
        r"\b(?:plus|with)\b(?=\s+[0-9])|&(?=\s*[0-9])",
        message,
        re.I,
    )
    result: list[Clause] = []
    start = 0
    for match in boundaries:
        if message[start : match.start()].strip():
            result.append(Clause(start, match.start(), message[start : match.start()]))
        start = match.end()
    if message[start:].strip():
        result.append(Clause(start, len(message), message[start:]))
    return result


# ISO 4217 codes and common currency names are a currency vocabulary, not a list
# of particular adversarial sentences. Only EUR/euro/€ (and Irish suffix e) are
# supported. An adjacent unknown uppercase three-letter code also fails closed.
_CODES = [
    "AED",
    "AFN",
    "ALL",
    "AMD",
    "ANG",
    "AOA",
    "ARS",
    "AUD",
    "AWG",
    "AZN",
    "BAM",
    "BBD",
    "BDT",
    "BGN",
    "BHD",
    "BIF",
    "BMD",
    "BND",
    "BOB",
    "BRL",
    "BSD",
    "BTN",
    "BWP",
    "BYN",
    "BZD",
    "CAD",
    "CDF",
    "CHF",
    "CLP",
    "CNY",
    "COP",
    "CRC",
    "CUP",
    "CVE",
    "CZK",
    "DJF",
    "DKK",
    "DOP",
    "DZD",
    "EGP",
    "ERN",
    "ETB",
    "EUR",
    "FJD",
    "FKP",
    "GBP",
    "GEL",
    "GHS",
    "GIP",
    "GMD",
    "GNF",
    "GTQ",
    "GYD",
    "HKD",
    "HNL",
    "HTG",
    "HUF",
    "IDR",
    "ILS",
    "INR",
    "IQD",
    "IRR",
    "ISK",
    "JMD",
    "JOD",
    "JPY",
    "KES",
    "KGS",
    "KHR",
    "KMF",
    "KPW",
    "KRW",
    "KWD",
    "KYD",
    "KZT",
    "LAK",
    "LBP",
    "LKR",
    "LRD",
    "LSL",
    "LYD",
    "MAD",
    "MDL",
    "MGA",
    "MKD",
    "MMK",
    "MNT",
    "MOP",
    "MRU",
    "MUR",
    "MVR",
    "MWK",
    "MXN",
    "MYR",
    "MZN",
    "NAD",
    "NGN",
    "NIO",
    "NOK",
    "NPR",
    "NZD",
    "OMR",
    "PAB",
    "PEN",
    "PGK",
    "PHP",
    "PKR",
    "PLN",
    "PYG",
    "QAR",
    "RON",
    "RSD",
    "RUB",
    "RWF",
    "SAR",
    "SBD",
    "SCR",
    "SDG",
    "SEK",
    "SGD",
    "SHP",
    "SLE",
    "SOS",
    "SRD",
    "SSP",
    "STN",
    "SVC",
    "SYP",
    "SZL",
    "THB",
    "TJS",
    "TMT",
    "TND",
    "TOP",
    "TRY",
    "TTD",
    "TWD",
    "TZS",
    "UAH",
    "UGX",
    "USD",
    "UYU",
    "UZS",
    "VES",
    "VND",
    "VUV",
    "WST",
    "XAF",
    "XCD",
    "XOF",
    "XPF",
    "YER",
    "ZAR",
    "ZMW",
    "ZWG",
]
_CURRENCY_WORD = (
    r"(?:" + "|".join(_CODES) + r"|euros?|dollars?|pounds?|sterling|yen|yuan|renminbi|"
    r"rupees?|roubles?|rubles?|kron[ae]|kron[eo]r|francs?|dirhams?|pesos?|bitcoin)"
)
_CURRENCY = rf"(?:[^\w\s.,;:()!?+\-−–]|\b(?i:{_CURRENCY_WORD})\b|\b[A-Z]{{3}}\b)"
_NEGATION = re.compile(
    r"\b(?:not|never|no|minus|negative|deduct|subtract|credit|refund|"
    r"unchanged|stay|stays|leave|keep)\b|\bdon['’]?t\b",
    re.I,
)
_UNCERTAIN = re.compile(
    r"\b(?:might|maybe|perhaps|possibly|uncertain|unsure|approximately|approx|"
    r"estimated|roughly|around|between|if|unless)\b|\bnot\s+(?:quite\s+)?sure\b",
    re.I,
)
_NEXT_ITEM = re.compile(
    r",\s+[0-9]+(?:\.[0-9]{1,2})?\s+[^\W\d_][\w'’ -]{0,300}?"
    r"\s+(?:at\s*€?|@\s*€?|€)\s*[0-9]",
    re.I,
)


def negative_clause(text: str) -> bool:
    """Do not infer a new positive number from negative/preservation instructions."""
    return _NEGATION.search(text) is not None


def financial_negative_clause(text: str) -> bool:
    # VAT registration is a separate fact, not the polarity of a charge.
    return negative_clause(
        re.sub(
            r"\b(?:not\s+(?:VAT\s+registered|registered\s+(?:for\s+)?VAT)|"
            r"no\s+VAT(?!\s+(?:[0-9]|rate|information|details|number|registration|status)))\b",
            "",
            text,
            flags=re.I,
        )
    )


def inherited_negative(message: str, clause: Clause, *, financial: bool = False) -> bool:
    prefix = re.split(r"[;\n!?]|\.(?=\s|$)", message[: clause.start])[-1]
    negative = financial_negative_clause(prefix) if financial else negative_clause(prefix)
    return (
        negative
        and re.match(
            r"\s*(?:actually\s+)?(?:make|change|set|update|rename|increase|reduce|use)\b",
            clause.text,
            re.I,
        )
        is None
    )


def _currency_is_supported(currency: str) -> bool:
    return currency.casefold() in {"€", "eur", "euro", "euros"}


def _currency_context_supported(message: str) -> bool:
    # Look on both sides of every digit expression, not just the selected number.
    # This rejects mixed currencies and currency/sign orders such as negative EUR.
    number = r"[+\-−–]?\s*[0-9][0-9,.]*(?:k|e)?"
    # Known codes also match the unknown-code alternative. Commit each lexical
    # match and the run so repeated currency words cannot cause exponential
    # backtracking when no valid number follows.
    chain = rf"(?P<chain>(?:(?>{_CURRENCY})\s*)++)"
    for pattern in (
        rf"{chain}{number}",
        rf"{number}\s*{chain}",
    ):
        for match in re.finditer(pattern, message):
            for part in re.finditer(_CURRENCY, match.group("chain")):
                currency = part.group().strip()
                if _currency_is_supported(currency):
                    continue
                # Punctuation is not currency; Unicode Sc and reviewed currency
                # words/codes are. The broad symbol capture preserves TLS-free,
                # dependency-free Unicode currency recognition.
                if (
                    any(unicodedata.category(char) == "Sc" for char in currency)
                    or currency == "₿"
                    or re.fullmatch(_CURRENCY_WORD, currency, re.I)
                    or re.fullmatch(r"[A-Z]{3}", currency)
                    and currency not in {"VAT", "QTY"}
                ):
                    return False
    return True


def numeric_tokens(message: str, *, allow_percentage: bool = False) -> list[NumericToken]:
    normalised = re.sub(r"(?<=[0-9])[xX×](?=[0-9])", " ", message)
    normalised = re.sub(
        r"\b(?:EUR|euros?)\s*(?=[0-9])",
        lambda match: " " * len(match.group()),
        normalised,
        flags=re.I,
    )
    unsupported = [
        match.span()
        for match in re.finditer(r"\b[0-9]+(?:\.[0-9]+)?\s*[eE]\s*[+\-]?\s*[0-9]+\b", message)
    ]
    unsupported.extend(
        match.span(1)
        for match in re.finditer(r"(?=(\b[0-9][0-9.,]*\s*[+*/=\-]\s*€?\s*[0-9][0-9.,]*))", message)
    )
    result: list[NumericToken] = []
    for match in re.finditer(
        r"(?<![\w.,])(?P<number>[+-]?[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"
        r"(?P<scale>k)?(?:euros?|eur|e)?(?![\w]|[.,][0-9])",
        normalised,
        re.I,
    ):
        prefix, suffix = message[: match.start()], message[match.end() :]
        currency = rf"(?:€|{_CURRENCY_WORD})"
        if (
            match.group("number").startswith(("-", "+"))
            or ("." in match.group("number") and len(match.group("number").rsplit(".", 1)[1]) > 2)
            or re.search(rf"[+\-−–]\s*(?:{currency}\s*)?$", prefix, re.I)
            or re.search(rf"\b(?:minus|negative)\s*(?:{currency}\s*)?$", prefix, re.I)
            or re.search(r"\b0[xX][0-9a-fA-F]+\b", message[max(0, match.start() - 2) : match.end()])
            or any(left <= match.start() < right for left, right in unsupported)
            or (not allow_percentage and re.match(r"\s*(?:%|per\s*cent\b|percent\b)", suffix, re.I))
            or re.match(r"\.[.\s]*[0-9]", suffix)
            # A comma followed by spaced digits is unsupported decimal/grouping
            # syntax unless it explicitly starts another quantity/item/price.
            or (re.match(r",\s+[0-9]", suffix) and not _NEXT_ITEM.match(suffix))
            or (
                re.search(rf"\(\s*(?:{currency}\s*)?$", prefix, re.I) and re.match(r"\s*\)", suffix)
            )
        ):
            continue
        value = Decimal(match.group("number").replace(",", ""))
        result.append(
            NumericToken(match.start(), match.end(), value * (1000 if match.group("scale") else 1))
        )
    return result


def expression_context_safe(message: str, tokens: list[NumericToken]) -> bool:
    if not _currency_context_supported(message) or _UNCERTAIN.search(message):
        return False
    # Alternatives can omit both the second currency and the second VAT label.
    raw_numbers = list(re.finditer(r"[0-9]+(?:[.,][0-9]+)*", message))
    if len(raw_numbers) > 1 and re.search(r"\bor\b|\bversus\b|\bvs\.?\b", message, re.I):
        return False
    return not (
        len(raw_numbers) > 1
        and re.search(
            r"\b(?:from|was|were|previously|formerly|originally)\b|\binstead\s+of\b",
            message,
            re.I,
        )
        is not None
    )


def _complete_clause_safe(message: str) -> bool:
    raw_numbers = list(re.finditer(r"[0-9]+(?:[.,][0-9]+)*", message))
    currency = rf"(?:€|(?i:{_CURRENCY_WORD}))"
    if (
        re.search(r"[0-9][\s\u00a0\u202f'’]+[0-9]", message)
        or re.search(r"[0-9]\s+(?:k|hundred|thousand|million|billion)\b", message, re.I)
        or re.search(r"[0-9][0-9.]*\s*[eE]\s*[+\-−–]?\s*[0-9]", message)
        or re.search(r"[0-9]\s+[.,]\s*[0-9]|[0-9][.,]\s+[0-9]", message)
        or re.search(r"[0-9][.,]{2,}[0-9]", message)
        or re.search(
            rf"[0-9][0-9.,]*\s*(?:{currency}\s*)?[+*/=−–×÷-]\s*(?:{currency}\s*)?[0-9]", message
        )
    ):
        return False
    for raw in raw_numbers:
        prefix, suffix = message[: raw.start()], message[raw.end() :]
        if (
            re.search(rf"\(\s*(?:{currency}\s*)*$", prefix)
            and re.match(rf"\s*(?:{currency}\s*)*\)", suffix)
            or re.match(rf"\s*(?:{currency}\s*)*[+\-−–](?![\w])", suffix)
        ):
            return False
    return True


def _monetary(token: NumericToken, message: str) -> bool:
    return bool(
        re.search(r"(?:€|\b(?:EUR|euros?))\s*$", message[: token.start], re.I)
        or re.match(r"\s*(?:€|EUR\b|euros?\b|e\b)", message[token.end :], re.I)
        or re.search(r"(?:euros?|eur|e)$", message[token.start : token.end], re.I)
    )


def role_matches(
    role: str | None,
    token: NumericToken,
    message: str,
    clause: Clause,
    item_description: str | None = None,
) -> bool:
    text = clause.text
    start, end = token.start - clause.start, token.end - clause.start
    prefix, suffix = text[:start], text[end:]
    if role in {"quantity", "unit_price"}:
        monetary = _monetary(token, message)
        quantity = bool(re.search(r"\b(?:quantity|qty)\s*(?:(?:is|to|of|:|=)\s*)?$", prefix, re.I))
        without_currency = re.sub(r"(?:€|\b(?:EUR|euros?))\s*$", "", prefix, flags=re.I)
        price = bool(
            monetary
            and not re.search(r"\b(?:total|subtotal|overall|deposit)\b", text, re.I)
            or re.search(
                r"(?:\b(?:at|price|cost|each|apiece)|@)\s*(?:(?:is|to|of|:|=)\s*)?$",
                without_currency,
                re.I,
            )
            or re.match(r"\s*(?:each|apiece|per\s+(?:item|unit))\b", suffix, re.I)
        )
        if role == "unit_price":
            # A line cannot silently select one of several possible prices.
            candidates = [
                candidate for candidate in numeric_tokens(text) if _monetary(candidate, text)
            ]
            return price and not quantity and len(candidates) <= 1
        # A quantity precedes its noun (3 valves) or follows a quantity label.
        # Currency/price markers can never supply a quantity.
        noun = (
            item_description is not None
            and re.match(r"\s+" + re.escape(item_description) + r"(?!\w)", suffix, re.I) is not None
        )
        return not price and (quantity or noun)
    if role in {"amount", "labour", "materials"}:
        # Quantity shorthand is not a stated scalar charge. Neither operand
        # supplies the amount, even when only the price has a currency marker.
        if re.search(r"(?<!\w)[0-9][0-9.,]*\s*[xX]\s*(?:€|EUR|euros?)?\s*[0-9]", text, re.I):
            return False
        labels = list(
            re.finditer(r"\b(labou?r|materials?|amount|total|charge|price)\b", text, re.I)
        )
        preceding = [
            label
            for label in labels
            if label.end() <= start and not re.search(r"[0-9]", text[label.end() : start])
        ]
        following = [
            label
            for label in labels
            if label.start() >= end
            and re.fullmatch(r"\s*(?:for|on)\s*", text[end : label.start()], re.I)
        ]
        label = following[0] if following else preceding[-1] if preceding else None
        if label:
            found = label.group().casefold()
            actual = (
                "labour"
                if found in {"labour", "labor"}
                else ("materials" if found in {"material", "materials"} else "amount")
            )
            return actual == role
        # Multiple unlabelled numbers are not a determinate scalar update.
        monetary_candidates = [
            candidate for candidate in numeric_tokens(message) if _monetary(candidate, message)
        ]
        if monetary_candidates:
            return len(monetary_candidates) == 1 and token == monetary_candidates[0]
        return len(numeric_tokens(message)) == 1
    return True


def numeric_evidence(
    value: str,
    evidence: str,
    message: str | None = None,
    *,
    allow_percentage: bool = False,
    within: str | None = None,
    role: str | None = None,
    item_description: str | None = None,
) -> bool:
    original = evidence if message is None else message
    spans = evidence_spans(original, evidence)
    contexts = [(0, len(original))]
    if within is not None:
        contexts = evidence_spans(original, within)
        spans = [
            (start, end)
            for start, end in spans
            if any(start < right and left < end for left, right in contexts)
        ]
    tokens = numeric_tokens(original, allow_percentage=allow_percentage)
    if not expression_context_safe(original, tokens):
        return False
    target = Decimal(value)
    source_clauses = clauses(original)
    return bool(spans) and all(
        any(
            token.value == target
            and start <= token.start
            and token.end <= end
            and any(left <= token.start and token.end <= right for left, right in contexts)
            and any(
                clause.start <= token.start
                and token.end <= clause.end
                and _complete_clause_safe(clause.text)
                and (allow_percentage or not financial_negative_clause(clause.text))
                and (allow_percentage or not inherited_negative(original, clause, financial=True))
                and role_matches(role, token, original, clause, item_description)
                for clause in source_clauses
            )
            for token in tokens
        )
        for start, end in spans
    )
