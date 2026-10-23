"""Bounded assertion context over unchanged, absolute source spans.

Callers recognise numbers and VAT treatments. This module only retains their
surrounding intent, document reference and formatted heading; it does not infer
amounts, tax treatments or corrections from prose.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class AssertionIntent(StrEnum):
    AFFIRMATIVE = "affirmative"
    QUESTION = "question"
    OPTION = "option"
    NEGATED = "negated"
    CONDITIONAL = "conditional"
    AMBIGUOUS = "ambiguous"


class DocumentScope(StrEnum):
    CURRENT = "current"
    HISTORICAL = "historical"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class AssertionContext:
    start: int
    end: int
    expression: str
    clause_start: int
    clause_end: int
    intent: AssertionIntent
    document_scope: DocumentScope
    heading_start: int | None
    document_heading_start: int | None = None


_HARD_BOUNDARY = re.compile(r"[;\n!?]|\.(?=\s|$)")
_SOFT_BOUNDARY = re.compile(r",(?![0-9])|\b(?:and|but)\b", re.I)
_DOCUMENT = re.compile(
    r"\b(?P<historical>old|previous|earlier|last)\s+(?:job|invoice|bill)\b|"
    r"\b(?P<current>this|current|new)\s+(?:job|invoice|bill)\b|"
    r"\b(?:invoice|bill|job)\s+(?P<preparing>being\s+prepared)\b",
    re.I,
)
_QUESTION = re.compile(
    r"^\s*(?:is|are|do|does|should|could|would|can|will|"
    r"what|which|how|why|when|where|who|whose)\b",
    re.I,
)
_NEGATIVE = re.compile(
    r"\b(?:not|never|no|minus|negative|deduct|subtract|credit|refund|"
    r"unchanged|stay|stays|leave|keep|cannot)\b|"
    r"\b(?:don|doesn|didn|isn|aren|wasn|weren|can|couldn|wouldn|shouldn|"
    r"won|shan|haven|hasn|hadn|mustn|needn)['’]?t\b",
    re.I,
)
_RESET_VERB = re.compile(
    r"^\s*(?:actually\s+)?(?:make|change|set|update|rename|increase|reduce|use|apply|charge)\b",
    re.I,
)
_CONDITIONAL = re.compile(r"\b(?:if|unless)\b", re.I)
_AMBIGUOUS = re.compile(
    r"\b(?:might|maybe|perhaps|possibly|uncertain|unsure|approximately|approx|"
    r"estimated|roughly|around|between)\b",
    re.I,
)


def _presented(text: str) -> str:
    """Inspect presentation markers without changing source coordinates."""
    return re.sub(
        r"^\s*[:;]*\s*(?:(?:[-*•+]|[0-9]+[.)]|[a-z][.)]|\([a-z0-9]+\))\s+)?",
        "",
        text,
        flags=re.I,
    )


def _question_head(text: str) -> bool:
    return bool(_QUESTION.match(text) and re.match(r"\s*(?:do|does)\s+not\b", text, re.I) is None)


def _listed_segment(message: str, start: int, end: int) -> bool:
    line_start = max(message.rfind(mark, 0, start) for mark in ("\n", ";", "?")) + 1
    return (
        re.match(
            r"^\s*:*\s*(?:[-*•+]|[0-9]+[.)]|[a-z][.)]|\([a-z0-9]+\))\s+",
            message[line_start:end],
            re.I,
        )
        is not None
    )


def _heading_intent(text: str, topic: Literal["financial", "vat"]) -> AssertionIntent | None:
    content = _presented(text).strip().rstrip(":").strip()
    if topic == "financial" and re.search(r"\bvat\b", content, re.I):
        return None
    if re.fullmatch(
        r"(?:(?:vat|financial)\s+)?(?:options?|choices?|alternatives?)(?:\s+for\s+vat)?|"
        r"(?:choose|select)(?:\s+(?:one|vat(?:\s+(?:treatment|rate))?))?|either",
        content,
        re.I,
    ):
        return AssertionIntent.OPTION
    subject = (
        r"\bvat\b"
        if topic == "vat"
        else r"\b(?:vat|amount|charge|price|cost|total|labou?r|materials?|quantity|qty|unit)\b"
    )
    if _question_head(content) and re.search(subject, content, re.I):
        return AssertionIntent.QUESTION
    return None


def _topic_instruction(text: str, topic: Literal["financial", "vat"]) -> bool:
    subject = (
        r"\bvat\b"
        if topic == "vat"
        else r"\b(?:amount|charge|price|cost|total|labou?r|materials?|quantity|qty|unit)\b|€"
    )
    if re.search(subject, text, re.I) is None:
        return False
    action = r"\b(?:use|uses|set|apply|charge|make|change|update|increase|reduce)\b"
    predicate = (
        r"\b(?:is|are)\s+(?:(?:including|excluding|inclusive|exclusive|before|plus|no)\s+)?vat\b|"
        r"\bvat\s+(?:rate\s+)?(?:is|at)\b"
        if topic == "vat"
        else r"\b(?:is|are)\s*(?:€|[0-9])"
    )
    return bool(
        re.search(rf"{action}[^;\n!?]*(?:{subject})", text, re.I)
        or re.search(predicate, text, re.I)
    )


def _document_scope(text: str) -> DocumentScope | None:
    documents = list(_DOCUMENT.finditer(text))
    if not documents:
        return None
    return DocumentScope.HISTORICAL if documents[-1].group("historical") else DocumentScope.CURRENT


def _registration_facts(text: str, expression: str) -> str:
    # Registration/no-VAT facts are not negative instructions about a charge.
    result = re.sub(
        r"\b(?:not\s+(?:VAT\s+registered|registered\s+(?:for\s+)?VAT)|"
        r"no\s+VAT(?!\s+(?:[0-9]|rate|information|details|number|registration|status)))\b",
        "",
        text,
        flags=re.I,
    )
    if re.fullmatch(r"no\s+vat", expression, re.I):
        result = re.sub(r"\bnot\s+registered\b", "", result, flags=re.I)
    return result


def _local_intent(
    message: str,
    start: int,
    end: int,
    statement_start: int,
    statement_end: int,
    clause_start: int,
    clause_end: int,
) -> AssertionIntent:
    expression = message[start:end]
    statement = _presented(message[statement_start:statement_end])
    clause = _presented(message[clause_start:clause_end])
    before, after = message[statement_start:start], message[end:statement_end]
    if (
        message[statement_end : statement_end + 1] == "?"
        or _question_head(statement)
        or _question_head(clause)
        or re.match(r"\s*(?:,|\b(?:and|but)\b)\s*", after, re.I)
        and _question_head(re.sub(r"^\s*(?:,|\b(?:and|but)\b)\s*", "", after, flags=re.I))
    ):
        return AssertionIntent.QUESTION
    local = message[clause_start:start] + " " + message[end:clause_end]
    inherited = message[statement_start:clause_start]
    uncertainty_context = inherited + local
    if _CONDITIONAL.search(uncertainty_context):
        return AssertionIntent.CONDITIONAL
    if _AMBIGUOUS.search(uncertainty_context):
        return AssertionIntent.AMBIGUOUS
    if _RESET_VERB.match(clause) or (
        _document_scope(clause) == DocumentScope.CURRENT
        and _document_scope(inherited) == DocumentScope.HISTORICAL
    ):
        inherited = ""
    context = _registration_facts(inherited + local, expression)
    if _NEGATIVE.search(context):
        return AssertionIntent.NEGATED
    assessment = r"(?:incorrect|wrong|false|invalid|mistaken|inapplicable)"
    before = re.sub(r"(?:\s*(?:,|\b(?:and|but)\b))+\s*$", "", before, flags=re.I)
    after = re.sub(r"^\s*(?:(?:,|\b(?:and|but)\b)\s*)*", "", after, flags=re.I)
    if re.search(rf"\b{assessment}\s*$", before, re.I) or re.match(
        rf"\s*(?:(?:this|that|it)\s+)?"
        rf"(?:(?:is|are|was|were|seems?|looks?|would\s+be)\s+)?"
        rf"(?:(?:definitely|clearly|actually)\s+)?{assessment}\b",
        after,
        re.I,
    ):
        return AssertionIntent.NEGATED
    if re.search(r"\b(?:choose|choice|either|between)\b", before, re.I):
        return AssertionIntent.OPTION
    return AssertionIntent.AFFIRMATIVE


def assertion_context(
    message: str,
    start: int,
    end: int,
    *,
    topic: Literal["financial", "vat"] = "financial",
) -> AssertionContext:
    """Classify a caller-recognised expression in its complete original input."""
    if not 0 <= start < end <= len(message):
        raise ValueError("invalid assertion source span")
    boundaries = list(_HARD_BOUNDARY.finditer(message))
    statement_start = max((part.end() for part in boundaries if part.end() <= start), default=0)
    statement_end = next((part.start() for part in boundaries if part.start() >= end), len(message))
    soft = list(_SOFT_BOUNDARY.finditer(message, statement_start, statement_end))
    clause_start = max(
        (part.end() for part in soft if part.end() <= start), default=statement_start
    )
    clause_end = next((part.start() for part in soft if part.start() >= end), statement_end)
    local_before = _document_scope(message[clause_start:start])
    local_after = _document_scope(message[end:clause_end])
    local_document = (
        local_before or local_after or _document_scope(message[statement_start:clause_start])
    )
    intent = _local_intent(
        message,
        start,
        end,
        statement_start,
        statement_end,
        clause_start,
        clause_end,
    )
    heading_start: int | None = None
    heading_intent: AssertionIntent | None = None
    document_heading: DocumentScope | None = None
    document_heading_start: int | None = None
    segment_start = 0
    for boundary in boundaries:
        if boundary.start() > start:
            break
        segment = message[segment_start : boundary.start()]
        candidate = _heading_intent(segment, topic)
        segment_document = _document_scope(segment)
        independent_current = (
            segment_document == DocumentScope.CURRENT
            and not _listed_segment(message, segment_start, boundary.start())
            and not _question_head(_presented(segment))
            and not _CONDITIONAL.search(segment)
            and not _AMBIGUOUS.search(segment)
            and not _NEGATIVE.search(_registration_facts(segment, ""))
        )
        # A document label owns its formatted continuation independently of a
        # question/options heading. A completed historical sentence does not
        # start such a frame. Preserve the unchanged source heading offset.
        if segment_document is not None and (
            segment.rstrip().endswith(":") or candidate is not None
        ):
            document_heading, document_heading_start = segment_document, segment_start
        elif independent_current:
            document_heading, document_heading_start = None, None
        if candidate is not None:
            heading_start, heading_intent = segment_start, candidate
        elif independent_current and _topic_instruction(segment, topic):
            heading_start, heading_intent = None, None
        segment_start = boundary.end()
    document = local_document or document_heading or DocumentScope.CURRENT
    if local_document is not None:
        document_heading_start = None
    prefix_heading = _heading_intent(message[statement_start:start], topic)
    if prefix_heading is not None:
        heading_start, heading_intent = statement_start, prefix_heading
    scoped_affirmative = (
        document == DocumentScope.CURRENT
        and _document_scope(message[statement_start:statement_end]) == DocumentScope.CURRENT
        and intent == AssertionIntent.AFFIRMATIVE
        and _topic_instruction(message[statement_start:statement_end], topic)
        and not _listed_segment(message, statement_start, statement_end)
    )
    if scoped_affirmative:
        heading_start, heading_intent = None, None
    if heading_intent is not None and intent == AssertionIntent.AFFIRMATIVE:
        intent = heading_intent
    return AssertionContext(
        start,
        end,
        message[start:end],
        clause_start,
        clause_end,
        intent,
        document,
        heading_start,
        document_heading_start,
    )
