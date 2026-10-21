"""Conservative source-expression grammar for untrusted extraction proposals.

Offsets always refer to the complete user input. Evidence selects an expression;
it cannot remove its currency, polarity, precision, clause or alternatives.
Unsupported language is a clarification, never permission to guess a value.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


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


class AmountScope(StrEnum):
    LINE_ITEM = "line_item"
    INVOICE = "invoice"
    PARTIAL = "partial"


@dataclass(frozen=True)
class ItemNumberRoles:
    quantity: bool
    unit_price: bool
    total_scope: AmountScope | None
    conflict: bool


def _invoice_scope(text: str, *, item_bound: bool = False) -> bool:
    """Scope words apply to their complete label, even with cropped evidence."""
    amount = r"(?:total|subtotal|amount|price|cost|value|balance|sum)"
    document = (
        r"(?:(?:the|this)\s+)?(?:(?:whole|entire|full)\s+)?(?:invoice|bill)(?:['’]s|[ -]wide)?"
    )
    # Qualifiers describe the document amount; they cannot narrow it to one
    # selected item. Keep these within the label rather than matching unrelated
    # uses of the verb "invoice" elsewhere in the item clause.
    qualifier = r"(?:(?:net|gross|final|outstanding|remaining|payable)\s+)*"
    due = r"(?:\s+(?:due|payable|outstanding))?"
    items = r"(?:all|both)\s+(?:items|lines)"
    return bool(
        re.search(
            r"\b(?:whole|entire|full|overall)\s+(?:invoice|bill)\b|"
            rf"\b{document}\s+{qualifier}{amount}\b|"
            rf"\b{amount}{due}\s+(?:(?:for|of|across|on)\s+)?{document}\b|"
            rf"\bgrand[ -]+{amount}\b|\boverall[ -]+(?:total|subtotal)\b|"
            rf"\b{amount}{due}\s+(?:for|of|across)\s+(?:the\s+)?{items}\b|"
            rf"\b{items}\s+{qualifier}{amount}\b",
            text,
            re.I,
        )
        or not item_bound
        and re.search(rf"\boverall\s+{amount}\b", text, re.I)
    )


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


def item_clauses(message: str, description: str) -> list[Clause]:
    """Item connectors retain their boundary even when quantity/currency is omitted."""
    selector = re.compile(r"(?<!\w)" + re.escape(description) + r"(?!\w)", re.I)
    names = list(selector.finditer(message))
    result: list[Clause] = []
    for clause in clauses(message):
        start = clause.start
        for connector in re.finditer(r"\b(?:plus|with)\b|&", clause.text, re.I):
            left, right = clause.start + connector.start(), clause.start + connector.end()
            if any(name.start() <= left and right <= name.end() for name in names):
                continue
            if not re.search(r"[0-9]", message[right : clause.end]):
                continue
            if message[start:left].strip():
                result.append(Clause(start, left, message[start:left]))
            start = right
        if message[start : clause.end].strip():
            result.append(Clause(start, clause.end, message[start : clause.end]))
    # A work-description mention such as "supply valves" carries no competing
    # numeric instruction. Count malformed numbers too so they cannot disappear.
    numeric_assertions = {
        clause.start
        for clause in result
        if selector.search(clause.text) and re.search(r"[0-9]", selector.sub("", clause.text))
    }
    if numeric_assertions:
        return [
            clause
            for clause in result
            if not selector.search(clause.text) or clause.start in numeric_assertions
        ]
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
_FOREIGN_CURRENCY_NAMES = (
    r"dollars?|pounds?|sterling|yen|yuan|renminbi|rupees?|roubles?|rubles?|"
    r"kron[ae]|kron[eo]r|crowns?|francs?|dirhams?|pesos?|bitcoin"
)
_CURRENCY_WORD = r"(?:" + "|".join(_CODES) + r"|euros?|" + _FOREIGN_CURRENCY_NAMES + r")"
_CURRENCY = rf"(?:[^\w\s.,;:()!?+\-−–]|\b(?i:{_CURRENCY_WORD})\b|\b[A-Z]{{3}}\b)"
_FOREIGN_CODE = r"(?:" + "|".join(code for code in _CODES if code != "EUR") + r")"
_QUALIFIED_FOREIGN_CODE = re.compile(
    rf"\(\s*{_FOREIGN_CODE}\s*\)|"
    rf"\b(?:in|currency(?:\s+is)?|denominated(?:\s+in)?)\s+{_FOREIGN_CODE}\b|"
    rf"\b{_FOREIGN_CODE}\s+(?:amount|price|cost|charge|total|labou?r|materials?)"
    r"\s*(?:(?:is|of|to)\s+|[:=]\s*)?€?\s*[0-9]",
    re.I,
)
_NEGATION = re.compile(
    r"\b(?:not|never|no|minus|negative|deduct|subtract|credit|refund|"
    r"unchanged|stay|stays|leave|keep|cannot)\b|"
    r"\b(?:don|doesn|didn|isn|aren|wasn|weren|can|couldn|wouldn|shouldn|"
    r"won|shan|haven|hasn|hadn|mustn|needn)['’]?t\b",
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


def nonassertive_expression(message: str, clause: Clause, start: int, end: int) -> bool:
    """Retain questions and rejected assertions across soft clause boundaries."""
    boundaries = list(re.finditer(r"[;\n!?]|\.(?=\s|$)", message))
    sentence_start = max((part.end() for part in boundaries if part.end() <= start), default=0)
    sentence_end = next((part.start() for part in boundaries if part.start() >= end), len(message))
    before, after = message[sentence_start:start], message[end:sentence_end]
    # Numeric spans omit spaced currency/percentage/unit labels; VAT callers
    # supply the complete assertion. Neither representation may hide its suffix.
    after = re.sub(
        r"^\s*(?:(?:€|EUR\b|euros?\b|e\b|%|per\s*cent\b|percent\b|"
        r"each\b|apiece\b|per\s+(?:item|unit)\b)\s*)*(?:VAT\b\s*)?",
        "",
        after,
        flags=re.I,
    )
    before = re.sub(r"(?:\s*(?:,|\b(?:and|but)\b))+\s*$", "", before, flags=re.I)
    continued = re.match(r"^\s*(?:,|\b(?:and|but)\b)", after, re.I) is not None
    after = re.sub(r"^\s*(?:(?:,|\b(?:and|but)\b)\s*)*", "", after, flags=re.I)
    assessment = r"(?:incorrect|wrong|false|invalid|mistaken|inapplicable)"
    question = (
        r"\s*(?:is|are|do|does|should|could|would|can|will|"
        r"what|which|how|why|when|where|who|whose)\b"
    )
    predicate = re.sub(
        r"^\s*(?:(?:this|that|it)\s+)?(?:(?:is|are|was|were)\s+)?", "", after, flags=re.I
    )
    first_word = re.match(r"[\w'’]+", predicate)
    registration_confirmation = (
        re.fullmatch(r"no\s+VAT", message[start:end], re.I) is not None
        and re.fullmatch(r"not\s+registered", after, re.I) is not None
    )
    return bool(
        message[sentence_end : sentence_end + 1] == "?"
        or re.match(question, clause.text, re.I)
        or re.match(question, message[sentence_start:start], re.I)
        or continued
        and re.match(question, after, re.I)
        or re.search(rf"\b{assessment}\s*$", before, re.I)
        or re.match(
            rf"\s*(?:(?:this|that|it)\s+)?"
            rf"(?:(?:is|are|was|were|seems?|looks?|would\s+be)\s+)?"
            rf"(?:(?:definitely|clearly|actually)\s+)?{assessment}\b",
            after,
            re.I,
        )
        or first_word is not None
        and negative_clause(first_word.group())
        and financial_negative_clause(predicate)
        and not registration_confirmation
    )


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
    # Currency names remain meaningful with country qualifiers or other words
    # between them and the digits ("500 New Zealand dollars"). Do not treat a
    # cropped number as EUR merely because the currency is not adjacent.
    if re.search(rf"\b(?:{_FOREIGN_CURRENCY_NAMES})\b", message, re.I):
        return False
    # An annotation can be separated from the digits by a preposition, field
    # label or parentheses. Symbols and explicit uppercase ISO codes remain
    # currency evidence throughout the original input. Case-insensitive codes
    # also match reviewed currency syntax, without making ordinary words such as
    # "all labour" or "pen tray" currencies merely because they share a code.
    if (
        any(unicodedata.category(char) == "Sc" and char != "€" for char in message)
        or "₿" in message
        or re.search(rf"\b{_FOREIGN_CODE}\b", message)
        or _QUALIFIED_FOREIGN_CODE.search(message)
    ):
        return False
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


def _item_number_tokens(text: str, description: str | None) -> list[NumericToken]:
    names = (
        list(re.finditer(r"(?<!\w)" + re.escape(description) + r"(?!\w)", text, re.I))
        if description is not None
        else []
    )
    return [
        token
        for token in numeric_tokens(text)
        if not any(name.start() <= token.start and token.end <= name.end() for name in names)
    ]


def _item_number_roles(
    token: NumericToken,
    text: str,
    description: str | None,
    tokens: list[NumericToken],
) -> ItemNumberRoles:
    """Keep the monetary scope separate from quantity and unit-price roles."""
    previous = max((other.end for other in tokens if other.end <= token.start), default=0)
    following = min(
        (other.start for other in tokens if other.start >= token.end), default=len(text)
    )

    prefix, suffix = text[: token.start], text[token.end :]
    before, after = text[previous : token.start], text[token.end : following]
    if description is not None:
        before = re.sub(r"(?<!\w)" + re.escape(description) + r"(?!\w)", "", before, flags=re.I)
    before = re.sub(r"(?:€|\b(?:EUR|euros?))\s*$", "", before, flags=re.I)
    after = re.sub(r"^\s*(?:€|EUR\b|euros?\b|e\b)", "", after, flags=re.I)
    labelled_quantity = bool(
        re.search(r"\b(?:quantity|qty)\s*(?:(?:is|to|of|:|=)\s*)?$", prefix, re.I)
    )
    noun_quantity = bool(
        description is not None
        and re.match(r"\s+" + re.escape(description) + r"(?!\w)", suffix, re.I)
    )
    quantity_total = (
        noun_quantity
        and not _monetary(token, text)
        and bool(re.search(r"\btotal\s+of\s*$", before, re.I))
    )
    # A label between amounts belongs to the following amount. Only a final
    # postfix label can establish this token's scope; do not steal the next
    # invoice label from an explicitly stated unit price.
    invoice = _invoice_scope(before, item_bound=description is not None) or (
        following == len(text) and _invoice_scope(after, item_bound=description is not None)
    )
    total = not quantity_total and bool(
        re.search(r"\b(?:total|subtotal|overall|deposit)\b", before, re.I)
        or re.match(r"\s*(?:in\s+)?(?:total|subtotal|overall|deposit)\b", after, re.I)
        or invoice
    )
    partial = bool(re.search(r"\bdeposit\b", before + " " + after, re.I))
    scope = None
    if total:
        scope = (
            AmountScope.PARTIAL
            if partial
            else AmountScope.INVOICE
            if invoice
            else AmountScope.LINE_ITEM
        )
    per_unit = r"(?:each|apiece|per[ -]+(?:item|unit))"
    explicit_unit = bool(
        re.search(
            rf"\b(?:unit\s+(?:price|cost)|{per_unit})\s*(?:(?:is|to|of|:|=)\s*)?$", before, re.I
        )
        or re.match(rf"\s*{per_unit}\b", after, re.I)
    )
    price = bool(
        _monetary(token, text)
        or re.search(
            r"(?:\b(?:at|price|cost|each|apiece)|@)\s*(?:(?:is|to|of|:|=)\s*)?$",
            before,
            re.I,
        )
        or explicit_unit
    )
    # Generic labels never override a line total. Combining explicit unit and
    # total semantics on the same expression also requires clarification.
    return ItemNumberRoles(
        not price and (labelled_quantity or noun_quantity),
        price and not labelled_quantity and not total,
        scope,
        partial or total and explicit_unit,
    )


def _item_numbers_supported(text: str, description: str | None, tokens: list[NumericToken]) -> bool:
    names = (
        list(re.finditer(r"(?<!\w)" + re.escape(description) + r"(?!\w)", text, re.I))
        if description is not None
        else []
    )
    # An invalid second amount must not disappear from role/ambiguity checks.
    return all(
        any(token.start <= raw.start() and raw.end() <= token.end for token in tokens)
        or any(name.start() <= raw.start() and raw.end() <= name.end() for name in names)
        for raw in re.finditer(r"[0-9]+(?:[.,][0-9]+)*", text)
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
    if role in {"quantity", "unit_price"}:
        tokens = _item_number_tokens(text, item_description)
        # The supported item grammar has one quantity, unit price and total.
        # Reject longer unresolved numeric lists before repeated role scans.
        if len(tokens) > 3:
            return False
        roles = _item_number_roles(
            NumericToken(start, end, token.value), text, item_description, tokens
        )
        if role == "unit_price":
            # Bare at/price/cost values participate just like marked currency.
            candidates = [
                candidate
                for candidate in tokens
                if _item_number_roles(candidate, text, item_description, tokens).unit_price
            ]
            return (
                roles.unit_price
                and not roles.conflict
                and len(candidates) == 1
                and _item_numbers_supported(text, item_description, tokens)
            )
        return roles.quantity and not roles.conflict
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
    source_clauses = (
        item_clauses(original, item_description)
        if role in {"quantity", "unit_price"} and item_description is not None
        else clauses(original)
    )
    if role in {"quantity", "unit_price"}:
        source_clauses = [
            clause
            for clause in source_clauses
            if (
                item_description is None
                or re.search(
                    r"(?<!\w)" + re.escape(item_description) + r"(?!\w)", clause.text, re.I
                )
                is not None
            )
        ]
        if item_description is not None and len(source_clauses) != 1:
            return False
        source_clauses = [
            clause
            for clause in source_clauses
            if len(_item_number_tokens(clause.text, item_description)) <= 3
        ]
        if not source_clauses:
            return False
    return bool(spans) and all(
        any(
            token.value == target
            and start <= token.start
            and token.end <= end
            and any(left <= token.start and token.end <= right for left, right in contexts)
            and any(
                clause.start <= token.start
                and token.end <= clause.end
                and (
                    role not in {"quantity", "unit_price"}
                    or item_description is None
                    or re.search(
                        r"(?<!\w)" + re.escape(item_description) + r"(?!\w)", clause.text, re.I
                    )
                    is not None
                )
                and _complete_clause_safe(clause.text)
                and not nonassertive_expression(original, clause, token.start, token.end)
                and (allow_percentage or not financial_negative_clause(clause.text))
                and (allow_percentage or not inherited_negative(original, clause, financial=True))
                and role_matches(role, token, original, clause, item_description)
                for clause in source_clauses
            )
            for token in tokens
        )
        for start, end in spans
    )


def line_total_matches(
    quantity: str, unit_price: str, message: str, *, within: str, item_description: str
) -> bool:
    """A final item may not discard a stated total or silently round a quotient."""
    tokens = _item_number_tokens(within, item_description)
    if len(tokens) > 3:
        return False
    roles = [_item_number_roles(token, within, item_description, tokens) for token in tokens]
    # "A total of 3 valves" describes a quantity, unlike a monetary line total.
    labelled = re.sub(
        r"\btotal\s+of(?=\s+[0-9][0-9,.]*\s+" + re.escape(item_description) + r"(?!\w))",
        "",
        within,
        flags=re.I,
    )
    labelled = re.sub(
        r"(?<!\w)" + re.escape(item_description) + r"(?!\w)", "", labelled, flags=re.I
    )
    if not re.search(
        r"\b(?:total|subtotal|overall|deposit)\b", labelled, re.I
    ) and not _invoice_scope(labelled, item_bound=True):
        return True
    if (
        not expression_context_safe(message, numeric_tokens(message))
        or not _complete_clause_safe(within)
        or not _item_numbers_supported(within, item_description, tokens)
        or financial_negative_clause(within)
        or any(role.conflict for role in roles)
    ):
        return False
    totals = [
        token
        for token, role in zip(tokens, roles, strict=True)
        if role.total_scope == AmountScope.LINE_ITEM
    ]
    quantities = [token for token, role in zip(tokens, roles, strict=True) if role.quantity]
    prices = [token for token, role in zip(tokens, roles, strict=True) if role.unit_price]
    return (
        len(totals) <= 1
        and len(prices) <= 1
        and len(quantities) <= 1
        and all(role.quantity or role.unit_price or role.total_scope is not None for role in roles)
        and all(token.value == Decimal(quantity) for token in quantities)
        and all(token.value == Decimal(unit_price) for token in prices)
        and (not totals or Decimal(quantity) * Decimal(unit_price) == totals[0].value)
        # Invoice totals are checked against the complete result by the caller.
        # They never prove a line price in unit_price_evidence.
    )


def unit_price_evidence(
    value: str,
    evidence: str,
    message: str,
    *,
    quantity: str,
    within: str,
    item_description: str,
    allow_existing_quantity: bool = False,
) -> bool:
    """Accept a stated unit price or a model proposal proven by an exact product."""
    if not line_total_matches(
        quantity, value, message, within=within, item_description=item_description
    ):
        return False
    if numeric_evidence(
        value,
        evidence,
        message,
        within=within,
        role="unit_price",
        item_description=item_description,
    ):
        return True
    if not (
        re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?", value)
        and Decimal(value) > 0
        and (
            allow_existing_quantity
            or numeric_evidence(
                quantity,
                evidence,
                message,
                within=within,
                role="quantity",
                item_description=item_description,
            )
        )
    ):
        return False
    for clause in item_clauses(message, item_description):
        if clause.text != within or inherited_negative(message, clause, financial=True):
            continue
        tokens = _item_number_tokens(within, item_description)
        for token in tokens:
            if (
                _item_number_roles(token, within, item_description, tokens).total_scope
                != AmountScope.LINE_ITEM
            ):
                continue
            start, end = clause.start + token.start, clause.start + token.end
            if nonassertive_expression(message, clause, start, end):
                return False
            if any(
                left <= start and end <= right for left, right in evidence_spans(message, evidence)
            ):
                return True
    return False


def invoice_total_matches(
    message: str, total: Decimal | None, *, item_descriptions: tuple[str, ...]
) -> bool:
    """Check an explicit invoice total only against a complete, unambiguous sum.

    No tax, discount, deposit or allocation arithmetic is inferred. None means
    the caller cannot establish the invoice sum from the supported notes.
    """
    totals: list[Decimal] = []
    for clause in clauses(message):
        bound = any(
            re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", clause.text, re.I)
            for name in item_descriptions
        )
        if not _invoice_scope(clause.text, item_bound=bound):
            continue
        tokens = numeric_tokens(clause.text)
        if (
            not expression_context_safe(message, numeric_tokens(message))
            or not _complete_clause_safe(clause.text)
            or not _item_numbers_supported(clause.text, None, tokens)
            or financial_negative_clause(clause.text)
        ):
            return False
        scoped = [
            token
            for token in tokens
            if _item_number_roles(token, clause.text, None, tokens).total_scope
            == AmountScope.INVOICE
        ]
        if len(scoped) != 1:
            return False
        token = scoped[0]
        if nonassertive_expression(
            message, clause, clause.start + token.start, clause.start + token.end
        ):
            return False
        totals.append(token.value)
    return not totals or total is not None and all(value == total for value in totals)
