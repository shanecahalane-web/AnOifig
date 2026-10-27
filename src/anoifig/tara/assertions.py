"""Bounded assertion context over unchanged, absolute source spans.

Callers recognise numbers and VAT treatments. This module only retains their
surrounding intent, document reference and formatted heading; it does not infer
amounts, tax treatments or corrections from prose.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, cast

AssertionTopic = Literal["financial", "vat", "text"]
TextField = Literal["customer_name", "work_description", "customer_details"]


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
    r"\b(?:invoice|bill|job)\s+(?P<preparing>being\s+prepared)\b|"
    r"\b(?P<reference>this\s+one)\b|"
    r"\b(?P<transition>(?:now|instead)\s+(?:please\s+)?"
    r"(?:use|apply|set|make|change|charge|record|update))\b|"
    r"\b(?P<unclear_transition>instead)(?!\s+of\b)\b",
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
    result = text
    prefix = (
        r"^\s*[:;]*\s*(?:>\s*|\#{1,6}\s+|"
        r"(?:[-*•+]|[0-9]+[.)]|[a-z][.)]|\([a-z0-9]+\))\s+)"
    )
    while (stripped := re.sub(prefix, "", result, flags=re.I)) != result:
        result = stripped
    # Presentation is inspected only; all stored evidence and offsets continue
    # to refer to the unchanged message. Wrappers cannot hide a question head.
    return re.sub(r"[*_~`]+", "", result).strip()


def _question_head(text: str) -> bool:
    return bool(_QUESTION.match(text) and re.match(r"\s*(?:do|does)\s+not\b", text, re.I) is None)


def _listed_segment(message: str, start: int, end: int) -> bool:
    line_start = max(message.rfind(mark, 0, start) for mark in ("\n", ";", "?")) + 1
    return (
        re.match(
            r"^\s*[:*_~`]*\s*(?:>\s*|"
            r"(?:[-*•+]|[0-9]+[.)]|[a-z][.)]|\([a-z0-9]+\))\s+)",
            message[line_start:end],
            re.I,
        )
        is not None
    )


def _heading_intent(text: str, topic: AssertionTopic) -> AssertionIntent | None:
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
        r"\b(?:vat|tax|rate|treatment|basis|percentage|option)\b"
        if topic == "vat"
        else r"\b(?:customer|client|name|work|description|contact|details|address|change)\b"
        if topic == "text"
        else r"\b(?:vat|amount|charge|price|cost|total|labou?r|materials?|quantity|qty|unit)\b"
    )
    if _question_head(content) and (topic == "text" or re.search(subject, content, re.I)):
        return AssertionIntent.QUESTION
    return None


def _topic_instruction(text: str, topic: AssertionTopic) -> bool:
    subject = (
        r"\bvat\b"
        if topic == "vat"
        else r"\b(?:customer|client|name|work|description|contact|details|address)\b"
        if topic == "text"
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
    if documents[-1].group("historical"):
        return DocumentScope.HISTORICAL
    prior_historical = [document for document in documents[:-1] if document.group("historical")]
    if prior_historical:
        bridge = text[prior_historical[-1].end() : documents[-1].start()]
        if re.search(
            r'\b(?:says?|said|states?|stated|reads?|instruction|wording|quoted)\b|["“]',
            bridge,
            re.I,
        ):
            return DocumentScope.HISTORICAL
    if any(
        documents[-1].group(group) for group in ("reference", "transition", "unclear_transition")
    ) and any(document.group("historical") for document in documents[:-1]):
        # Commands reported within an old-document clause remain historical.
        # Independent clauses receive their own source context from the caller.
        return DocumentScope.HISTORICAL
    if documents[-1].group("unclear_transition"):
        return DocumentScope.AMBIGUOUS
    return DocumentScope.CURRENT


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
    topic: AssertionTopic = "financial",
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
        and (
            _document_scope(message[statement_start:statement_end]) == DocumentScope.CURRENT
            or topic == "text"
            and _RESET_VERB.match(_presented(message[statement_start:statement_end]))
        )
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


@dataclass(frozen=True)
class MutationTarget:
    """Application-selected field and captured item aliases, never model routing."""

    field: str
    item_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class MutationConstraint:
    context: AssertionContext
    fields: frozenset[str]
    item_names: frozenset[str]
    whole_document: bool
    item_reference: bool

    def affects(self, target: MutationTarget) -> bool:
        if self.whole_document:
            return True
        if self.item_names:
            return bool(self.item_names & {name.casefold() for name in target.item_names})
        if self.item_reference:
            return bool(target.item_names)
        return not self.fields or target.field in self.fields


_TEXT_LABEL = re.compile(
    r"\b(?P<customer_details>(?:(?:customer|client)(?:\s+contact)?|his|her|their)\s+details|"
    r"(?:contact|billing)\s+(?:details|address)|(?:customer\s+)?address)\b|"
    r"\b(?P<work_description>(?:work|job)\s+description|description)\b|"
    r"\b(?P<customer_name>(?:customer|client)(?:\s+name)?|name)\b",
    re.I,
)
_FIELD_LABELS: dict[str, str] = {
    "amount": r"\b(?:amount|total|charge)\b",
    "labour": r"\blabou?r\b",
    "materials": r"\bmaterials?\b",
    "vat_basis": r"\bvat\b",
    "vat_rate": r"\bvat\b",
}
_CANCEL = re.compile(
    r"\b(?:cancel|discard|abort|ignore|undo|retract|withdraw|scratch|scrap)\b|"
    r"\bnever\s+mind\b|\bno\s+(?:changes?|updates?)\b|"
    r"\b(?:do\s+not|don['’]t|never)\s+(?:(?:you|ever|please|actually)\s+)*"
    r"(?:make|apply|save|record|perform|use|change|"
    r"update|replace|set|charge)\b",
    re.I,
)
_PRESERVE = re.compile(r"\b(?:keep|leave|retain|preserve|unchanged)\b", re.I)


def _text_labels(message: str) -> tuple[re.Match[str], ...]:
    """Only clause selectors label fields; words inside their payload stay data."""
    result: list[re.Match[str]] = []
    boundaries = list(re.finditer(r"[;\n!?]|\.(?=\s|$)|,(?![0-9])|\b(?:and|but)\b", message, re.I))
    for label in _TEXT_LABEL.finditer(message):
        start = max((mark.end() for mark in boundaries if mark.end() <= label.start()), default=0)
        if any(start <= earlier.start() for earlier in result):
            continue
        prefix = _presented(message[start : label.start()])
        if (
            not prefix
            or re.fullmatch(r"(?:the|this|his|her|their)", prefix, re.I)
            or re.search(
                r"\b(?:set|change|update|correct|record|use|replace|make|add|keep|leave)(?:\s+the)?\s*$",
                prefix,
                re.I,
            )
            or _document_scope(prefix) is not None
            and re.search(r"\b(?:invoice|bill|job)\s*$", prefix, re.I)
        ):
            result.append(label)
    return tuple(result)


def mutation_constraints(
    message: str, item_names: tuple[str, ...]
) -> tuple[MutationConstraint, ...]:
    """Retain current vetoes, including clauses without a new numeric value.

    Named fields/items constrain their own changes. A document or unresolved
    deictic cancellation cannot be cropped away by selecting earlier evidence.
    """
    constraints: list[MutationConstraint] = []
    boundaries = list(
        re.finditer(r"[;\n!?]|\.(?=\s|$)|,(?![0-9])|\b(?:and|but|or)\b", message, re.I)
    )
    start = 0
    for end in [part.start() for part in boundaries] + [len(message)]:
        clause = message[start:end]
        verb = _CANCEL.search(clause) or _PRESERVE.search(clause)
        if verb is not None and any(label.end() <= verb.start() for label in _text_labels(clause)):
            # A field-owned text payload is data, including words such as
            # "keep" or "scrap" describing the work. Later independent vetoes
            # are still inspected in their own clauses.
            verb = None
        if verb is not None:
            context = assertion_context(
                message, start + verb.start(), start + verb.end(), topic="text"
            )
            if context.document_scope != DocumentScope.HISTORICAL:
                names = frozenset(
                    name.casefold()
                    for name in item_names
                    if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", clause, re.I)
                )
                fields = {
                    field
                    for field, pattern in _FIELD_LABELS.items()
                    if re.search(pattern, clause, re.I)
                }
                fields.update(match.lastgroup for match in _text_labels(clause) if match.lastgroup)
                if re.search(r"\bdescription\b", clause, re.I):
                    fields.add("description")
                document = not (names or fields) and bool(
                    re.search(
                        r"\b(?:invoice|bill|notes|everything|all\s+(?:changes|updates)|"
                        r"(?:this|that|the)\s+(?:change|update|modification))\b|\bas\s+is\b",
                        clause,
                        re.I,
                    )
                )
                document = document or bool(
                    re.search(
                        r"\b(?:this|that|the|all)\s+(?:changes?|updates?|modifications?)\b",
                        clause,
                        re.I,
                    )
                )
                constraints.append(
                    MutationConstraint(
                        context,
                        frozenset(fields),
                        names,
                        document,
                        bool(
                            re.search(
                                r"\b(?:(?:this|that|selected|these)\s+(?:line\s+)?items?|(?:line|item)\s+description)\b",
                                clause,
                                re.I,
                            )
                        ),
                    )
                )
        boundary = next((part for part in boundaries if part.start() == end), None)
        start = boundary.end() if boundary is not None else len(message)
    return tuple(constraints)


def validate_mutation_authority(
    message: str, targets: tuple[MutationTarget, ...], *, item_names: tuple[str, ...] = ()
) -> None:
    aliases = tuple(
        dict.fromkeys((*item_names, *(name for target in targets for name in target.item_names)))
    )
    for constraint in mutation_constraints(message, aliases):
        if constraint.whole_document or any(constraint.affects(target) for target in targets):
            raise ValueError("cancelled or preserved preparation details")


@dataclass(frozen=True)
class TextAssertion:
    field: TextField
    value: str
    context: AssertionContext


def _explicit_text_assertions(message: str) -> tuple[TextAssertion, ...]:
    result: list[TextAssertion] = []
    labels = list(_text_labels(message))
    for index, label in enumerate(labels):
        field = label.lastgroup
        if field not in {"customer_name", "work_description", "customer_details"}:
            continue
        end = next(
            (mark.start() for mark in _HARD_BOUNDARY.finditer(message, label.end())), len(message)
        )
        if index + 1 < len(labels):
            end = min(end, labels[index + 1].start())
        prefix = re.match(
            r"\s*(?:(?:is|are|was|were|to|as)\b\s*|[:=]\s*)?", message[label.end() : end], re.I
        )
        if prefix is None:
            continue
        start = label.end() + prefix.end()
        value = message[start:end].strip().rstrip(",")
        if value:
            result.append(
                TextAssertion(
                    cast(TextField, field),
                    value,
                    assertion_context(message, start, start + len(value), topic="text"),
                )
            )
    for statement in re.finditer(r"(?:^|[;\n!?]|\.(?=\s))([^;\n!?]+)", message):
        raw_start = statement.start(1)
        implicit = re.match(
            r"\s*(?:(?:invoice|for)\s+|(?:this|the\s+(?:current|new|old|previous|earlier|last))\s+"
            r"(?:invoice|bill)\s+(?:is\s+|was\s+)?for\s+|(?:it['’]?s|it\s+is)\s+)"
            r"(?P<name>.+?)(?=\s*(?:€|[0-9]|[:,.]|\bfor\b)|$)",
            statement.group(1),
            re.I,
        )
        if implicit is not None:
            start, end = implicit.span("name")
            value = implicit.group("name").strip()
            if (
                value
                and re.match(
                    r"(?:total|subtotal|amount|price|cost|net|gross|final|balance|reference|number|vat)\b",
                    value,
                    re.I,
                )
                is None
            ):
                result.append(
                    TextAssertion(
                        "customer_name",
                        value,
                        assertion_context(
                            message, raw_start + start, raw_start + end, topic="text"
                        ),
                    )
                )
    return tuple(result)


def _text_role_matches(
    message: str, start: int, end: int, field: TextField, *, allow_bare: bool
) -> bool:
    context = assertion_context(message, start, end, topic="text")
    statement_start = max(
        (mark.end() for mark in _HARD_BOUNDARY.finditer(message, 0, start)), default=0
    )
    prefix = message[statement_start:start]
    labels = [
        label
        for label in _text_labels(message)
        if statement_start <= label.start() and label.end() <= start
    ]
    if labels:
        return labels[-1].lastgroup == field
    presented = _presented(prefix)
    if field == "customer_name":
        return (
            bool(
                re.search(
                    r"(?:^\s*(?:for|invoice)\s*|\b(?:invoice|bill)\s+(?:is\s+)?for\s*|"
                    r"^\s*(?:it['’]?s|it\s+is)\s*)$",
                    presented,
                    re.I,
                )
            )
            or allow_bare
            and not presented
            and not message[end:].strip(" .!?\n")
        )
    if field == "work_description":
        return (
            bool(re.search(r"\bfor\s*$", prefix, re.I))
            or bool(re.fullmatch(r"\s*for\s+[^;:\n!?]+:\s*", prefix, re.I))
            or (
                not message[context.clause_start : start].strip()
                and not message[end : context.clause_end].strip(" .!?:\n")
                and (allow_bare or statement_start > 0 or context.clause_start > 0)
            )
        )
    return False


def text_evidence(
    field: TextField, value: str, evidence: str, message: str, *, allow_bare: bool = False
) -> bool:
    """A text value retains source role, polarity, document scope and conflicts."""
    spans = [match.span() for match in re.finditer(re.escape(evidence), message)]
    candidates = [
        (match.start(), match.end())
        for match in re.finditer(r"(?<!\w)" + re.escape(value) + r"(?!\w)", message, re.I)
        if (context := assertion_context(message, match.start(), match.end(), topic="text")).intent
        == AssertionIntent.AFFIRMATIVE
        and context.document_scope == DocumentScope.CURRENT
        and _text_role_matches(message, match.start(), match.end(), field, allow_bare=allow_bare)
    ]
    if not spans or not all(
        any(left <= start and end <= right for start, end in candidates) for left, right in spans
    ):
        return False
    for assertion in _explicit_text_assertions(message):
        if (
            assertion.field == field
            and assertion.context.intent == AssertionIntent.AFFIRMATIVE
            and assertion.context.document_scope == DocumentScope.CURRENT
            and not (
                value.casefold().rstrip(".!?,") == assertion.value.casefold().rstrip(".!?,")
                or value.casefold().startswith(assertion.value.casefold() + ";")
            )
        ):
            return False
    return True
