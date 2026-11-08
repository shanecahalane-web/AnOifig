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


def _heading_intent(
    text: str, topic: AssertionTopic, *, question_mark: bool = False
) -> AssertionIntent | None:
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
    if (question_mark or _question_head(content)) and (
        topic == "text" or re.search(subject, content, re.I)
    ):
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
    if re.search(
        r"\b(?:was|were|had|used|suggested|proposed|reported|recommended)\b", local, re.I
    ) and not (
        re.fullmatch(r"\s*actually\s*", after, re.I)
        and re.fullmatch(
            r"\s*(?:the\s+)?(?:labou?r|materials?|amount|total|price|charge)\s+"
            r"(?:was|were)\s*(?:€|EUR|euros?)?\s*",
            before,
            re.I,
        )
    ):
        return AssertionIntent.AMBIGUOUS
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
        candidate = _heading_intent(segment, topic, question_mark=boundary.group() == "?")
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
    if topic != "text" and text_payload_contains(message, start, end):
        intent = AssertionIntent.AMBIGUOUS
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
    applies_to_all_items: bool = False


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
            return (
                target.applies_to_all_items
                and target.field in self.fields
                or bool(self.item_names & {name.casefold() for name in target.item_names})
            )
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
_PRESERVE = re.compile(r"\b(?:keep|leave|retain|preserve|unchanged|stays?)\b", re.I)
_REFERENCE_FIELD = (
    r"(?:amount|price|unit\s+price|quantity|qty|rate|vat(?:\s+(?:rate|basis|treatment))?|"
    r"labou?r(?:\s+(?:amount|price|charge))?|materials?(?:\s+(?:amount|price|charge))?|"
    r"customer(?:\s+(?:name|details))?|work(?:\s+description)?|contact(?:\s+details)?|"
    r"name|address|description|instruction|change|update|information|details)"
)
_REFERENCE_PREDICATE = (
    r"(?:(?:['’]s|\s+(?:is|are|was|were))\b|"
    r"(?=\s+(?:incorrect|wrong|false|invalid|mistaken|inapplicable)\b))"
)
_BACK_REFERENCE = re.compile(
    r"^(?:(?:actually|sorry)\s+)?"
    rf"(?:it|(?:this|that|these|those)(?:\s+{_REFERENCE_FIELD})?|"
    rf"(?:the\s+)?{_REFERENCE_FIELD}){_REFERENCE_PREDICATE}",
    re.I,
)


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
            (
                not prefix
                or re.fullmatch(r"(?:the|this|his|her|their)", prefix, re.I)
                or _document_scope(prefix) is not None
                and re.search(r"\b(?:invoice|bill|job)\s*$", prefix, re.I)
            )
            and re.match(
                r"\s*(?:[:=]|(?:is|are|was|were|to|as|not|never|no|unchanged|stays?)\b)",
                message[label.end() :],
                re.I,
            )
            or re.fullmatch(
                r"(?:(?:please|actually|now|instead)\s+)*"
                r"(?:set|change|update|correct|record|use|replace|make|add|keep|leave)(?:\s+the)?",
                prefix,
                re.I,
            )
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
        labels = _text_labels(clause)
        # A later negative fact about a named field need not repeat its value or
        # use an imperative verb to revoke earlier authority for that field.
        denial = next(
            (
                re.search(r"\b(?:not|never|no)\b", clause[label.end() :], re.I)
                for label in labels
                if re.match(r"\s+(?:(?:is|are)\s+)?(?:not|never|no)\b", clause[label.end() :], re.I)
            ),
            None,
        )
        # Keep coordinates relative to the original clause, like other verbs.
        if denial is not None:
            denial = _NEGATIVE.search(clause)
        verb = _CANCEL.search(clause) or _PRESERVE.search(clause) or denial
        if (
            verb is not None
            and verb is not denial
            and any(label.end() <= verb.start() for label in labels)
        ):
            # A field-owned text payload is data, including words such as
            # "keep" or "scrap" describing the work. Later independent vetoes
            # are still inspected in their own clauses.
            verb = None
        if verb is not None:
            context = assertion_context(
                message, start + verb.start(), start + verb.end(), topic="text"
            )
            # A direct cancellation in its own clause must not inherit an old
            # document from a preceding comma/heading. An explicitly historical
            # report within this clause still retains its own document scope.
            direct_cancel = (
                _CANCEL.match(clause, verb.start()) is not None
                and re.fullmatch(
                    r"(?:(?:please|actually|now|instead)\s*)*",
                    _presented(clause[: verb.start()]),
                    re.I,
                )
                is not None
                and _document_scope(clause) != DocumentScope.HISTORICAL
            )
            if context.document_scope != DocumentScope.HISTORICAL or direct_cancel:
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


def text_payload_contains(message: str, start: int, end: int) -> bool:
    """A number in an explicitly owned text value cannot authorise money/VAT."""
    return any(
        assertion.context.start <= start and end <= assertion.context.end
        for assertion in _explicit_text_assertions(message)
        if _text_labels(message[assertion.context.clause_start : assertion.context.start])
    )


def _operational_words_supported(statement: str, item_names: tuple[str, ...]) -> bool:
    """Check the entire operational phrase, including text after its value.

    Names are opaque item selectors. All other words must belong to the bounded
    command grammar; unknown predicates do not become affirmative by default.
    Field-owned customer/work/contact payloads are handled separately.
    """
    remaining = statement
    if re.search(r"\bactually\s*$", remaining, re.I):
        remaining = re.sub(r"\b(?:was|were)\b", "is", remaining, flags=re.I)
    # Explicit quantity/name/at-price syntax may describe an item the proposal
    # leaves uncollected. Its opaque name is data for coverage only; item writes
    # must still pass the independent selector, numeric-role and total checks.
    remaining = re.sub(
        r"(?<!\w)[0-9]+(?:\.[0-9]+)?\s+[^\W\d_][\w '’/-]{0,300}?\s+at\s+"
        r"(?:€|EUR\s*)?[0-9][0-9.,]*",
        "",
        remaining,
        flags=re.I,
    )
    for name in sorted(item_names, key=len, reverse=True):
        remaining = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", " ", remaining, flags=re.I)
    remaining = re.sub(
        r"(?:euros?|EUR)?[0-9][0-9.,]*(?:euros?|EUR|k|e)?", " ", remaining, flags=re.I
    )
    remaining = re.sub(r"\b(?:and\s+)?that\s+is\s+correct\b", "", remaining, flags=re.I)
    remaining = re.sub(
        r"\b(?:please|sorry|actually|correction|now|instead|and|but|set|change|update|make|use|uses|apply|"
        r"charge|increase|reduce|rename|correct|replace|all|whole|entire|the|a|an|to|at|"
        r"is|are|it|its|thats|that|s|for|of|on|this|one|current|new|being|prepared|invoice|bill|job|amount|price|cost|"
        r"total|subtotal|grand|net|gross|final|due|balance|overall|both|deposit|in|or|labou?r|materials?|unit|"
        r"quantity|qty|each|apiece|per|item|items|line|description|so|with|vat|rate|tax|including|"
        r"included|excluding|inclusive|exclusive|incl|inc|excl|ex|before|plus|no|not|"
        r"registered|exempt|zero|rated|percent|cent|euros?|eur|e|k|thanks|cheers|"
        r"repairs?|boiler|work|hours?|hrs?|installation|replacement|wrong|valve|pen|tray)\b|[\s0-9€%.,:=@&/'’()-]+",
        "",
        remaining,
        flags=re.I,
    )
    return not remaining


def _captured_invoice_statement(statement: str, text_values: tuple[str, ...]) -> str:
    """Consume opaque captured data only in explicit invoice/for data slots."""
    result = statement
    for value in sorted(text_values, key=len, reverse=True):
        result = re.sub(
            r"^(invoice\s+|for\s+)" + re.escape(value) + r"(?!\w)",
            r"\1",
            result,
            flags=re.I,
        )
        result = re.sub(
            r"(\bfor\s+|:\s*)" + re.escape(value) + r"(?=\s*:|\s*$)",
            r"\1",
            result,
            flags=re.I,
        )
    return result


def invoice_command_prefix(text: str) -> bool:
    """An invoice imperative names a recipient, not a document reference."""
    # Inspect the entire recipient slot, so adverbs before a reporting predicate
    # cannot turn "recently issued to John" into a customer name. Work payloads
    # after `for` and values after a number/currency keep their own roles.
    recipient = re.split(r"€|[0-9]|\bfor\b", text, maxsplit=1, flags=re.I)[0]
    # The supported explicit current-document reference is not a past/status
    # report. Its following field facts still pass their normal role checks.
    recipient = re.sub(r"^\s*invoice\s+being\s+prepared\b", "invoice", recipient, flags=re.I)
    return (
        re.match(
            r"^\s*(?:please\s+)?invoice\s+"
            r"(?!(?:from|for|dated|of|on|in|at|reference|ref|number|code|count|quantity|duration|"
            r"is|was|were|has|have|had|been|issued|sent|paid|discussed|delivered|received|"
            r"settled|cancelled|canceled|prepared|drafted|approved|recorded|reported|"
            r"already|previously|last|previous|earlier|old|yesterday|status|copy|payment)\b)",
            text,
            re.I,
        )
        is not None
        and re.search(
            r"\b(?:was|were|has|have|had|been|issued|sent|paid|discussed|delivered|received|"
            r"settled|cancelled|canceled|prepared|drafted|approved|recorded|reported|"
            r"last|previous|earlier|old|yesterday)\b",
            recipient,
            re.I,
        )
        is None
    )


def _contact_data_fragment(statement: str, text_values: tuple[str, ...]) -> bool:
    """Recognise bounded contact data after a semicolon in a captured value.

    A captured value alone cannot consume an arbitrary later instruction. Only
    contact literals and single-token metadata labels have this continuation form.
    """
    if not any(
        statement.casefold() == part.strip().casefold()
        for value in text_values
        for part in value.split(";")[1:]
    ):
        return False
    return (
        re.fullmatch(
            r"[^\s;@]+@[^\s;@]+\.[^\s;@]+|"
            r"[+()0-9][\s()0-9-]{5,30}|"
            r"IBAN\s+[A-Z]{2}[0-9]{2}(?:\s*[A-Z0-9]){11,30}|"
            r"(?:private\s+)?(?:contact\s+)?(?:marker|reference|label)\s+[\w-]+",
            statement,
            re.I,
        )
        is not None
    )


def validate_statement_coverage(
    message: str, *, item_names: tuple[str, ...], text_values: tuple[str, ...]
) -> None:
    """Reject unparsed statements instead of discarding their possible authority.

    This envelope does not extract values. Field-specific validators still prove
    each value, polarity and scope. Unknown continuations, even without a new
    value, cannot be assumed harmless. Explicit text payloads remain data.
    """
    for raw in re.split(r"[;\n!?]|(?<!\bNo)\.(?=\s|$)", message, flags=re.I):
        statement = _presented(raw).strip(" ,:")
        if raw.rstrip().endswith(":") and re.fullmatch(r"[0-9]+", statement):
            raise ValueError("unresolved numeric heading")
        reference = _BACK_REFERENCE.match(statement)
        if reference is None:
            for name in dict.fromkeys(item_names):
                reference = re.match(
                    r"^(?:the\s+)?"
                    + re.escape(name)
                    + rf"(?:\s+{_REFERENCE_FIELD})?{_REFERENCE_PREDICATE}",
                    statement,
                    re.I,
                )
                if reference is not None:
                    break
        if reference and (
            _document_scope(statement[reference.end() :]) == DocumentScope.HISTORICAL
            or re.match(
                r"\s*(?:(?:definitely|clearly|actually)\s+)?"
                r"(?:incorrect|wrong|false|invalid|mistaken|inapplicable)\b",
                statement[reference.end() :],
                re.I,
            )
        ):
            # This qualifies an earlier assertion, rather than introducing an
            # independent old-document fact or another literal text value.
            raise ValueError("unresolved qualification of prior instruction")
        if any(statement.casefold() == value.casefold() for value in text_values):
            continue
        if _contact_data_fragment(statement, text_values):
            continue
        if any(
            re.fullmatch(
                r"(?:it['’]?s|it\s+is)\s+" + re.escape(new) + r",\s*not\s+" + re.escape(old),
                statement,
                re.I,
            )
            for new in text_values
            for old in text_values
            if new != old
        ):
            continue
        labels = _text_labels(statement)
        if not labels:
            continued = [part.strip() for part in _SOFT_BOUNDARY.split(statement) if part.strip()]
            if len(continued) > 1:
                # Classify independent continuations before considering document
                # scope. A historical clause cannot own a later current veto.
                validate_statement_coverage(
                    ";".join(continued), item_names=item_names, text_values=text_values
                )
                continue
        if not statement or _document_scope(statement) == DocumentScope.HISTORICAL:
            continue
        if re.match(
            r"^(?:the\s+)?(?:old|previous|earlier|last)\s+(?:invoice|bill|job)\b", statement, re.I
        ):
            current = re.split(r",\s*(?:but\s+)?|\bbut\s+", statement, flags=re.I)
            if len(current) > 1:
                validate_statement_coverage(
                    current[-1], item_names=item_names, text_values=text_values
                )
                continue
        if re.fullmatch(
            r"(?:(?:hello|hi|thanks|thank you|cheers|please)[ ,]*)+|"
            r"how are you|what time (?:tomorrow|today)|that is correct|"
            r"(?:can|could) you (?:get|make|prepare) an? invoice ready|"
            r"back to (?:that|this|the) (?:job|invoice|bill)",
            statement,
            re.I,
        ):
            continue
        # These independent, bounded work/contact statements do not refer to a
        # saved field or to an earlier instruction. Everything else still needs
        # an explicit supported subject below.
        if re.fullmatch(
            r"(?:(?:is|are|which)\s+(?:the\s+)?repairs?\s+(?:complete|apply)|"
            r"(?:choose\s+)?(?:repairs?|installation|replacement)"
            r"(?:\s+or\s+(?:repairs?|installation|replacement))*(?:\s+are\s+fine)?|"
            r"the\s+old\s+parts?\s+(?:is|are)\s+incorrect)|"
            r"call [\s+()0-9-]+|discount [0-9]+(?:\.[0-9]+)?%",
            statement,
            re.I,
        ):
            continue
        # Scoped vetoes have already been checked against the mutation targets.
        if _CANCEL.search(statement) or _PRESERVE.search(statement):
            control = re.sub(
                r"\b(?:cancel|discard|abort|ignore|undo|retract|withdraw|scratch|scrap|"
                r"keep|leave|retain|preserve|unchanged|stays?|existing|original|as|"
                r"customer|client|name|description|address|contact|details)\b",
                "",
                statement,
                flags=re.I,
            )
            if _operational_words_supported(control, (*item_names, *text_values)):
                continue
            # An opaque field payload may contain these words as data. Only a
            # leading control verb makes it a preservation/cancellation clause.
            if not _text_labels(statement) or re.match(
                r"^(?:please\s+)?(?:keep|leave|retain|preserve|cancel|ignore)\b", statement, re.I
            ):
                raise ValueError("unresolved preservation or cancellation clause")
        if labels:
            if re.match(r"\s*(?:was|were)\b", statement[labels[0].end() :], re.I):
                raise ValueError("historical text is not current authority")
            # A later field label cannot hide an unparsed leading instruction.
            prefix = statement[: labels[0].start()]
            leading = _SOFT_BOUNDARY.split(prefix)
            if len(leading) > 1:
                validate_statement_coverage(
                    ";".join(leading[:-1]), item_names=item_names, text_values=text_values
                )
            # Preserve punctuation inside a captured text value. Otherwise a
            # following clause must stand on its own, even when the proposal
            # does not update this text field.
            payload = re.sub(
                r"^\s*(?:(?:is|are|to|as)\b\s*|[:=]\s*)?",
                "",
                statement[labels[0].end() :],
                flags=re.I,
            )
            if not any(payload.casefold() == value.casefold() for value in text_values):
                continued = _SOFT_BOUNDARY.split(payload)
                if len(continued) > 1:
                    validate_statement_coverage(
                        ";".join(continued[1:]), item_names=item_names, text_values=text_values
                    )
            continue
        if any(
            re.fullmatch(r"(?:for|invoice)\s+" + re.escape(value), statement, re.I)
            for value in text_values
        ):
            continue
        content = re.sub(
            r"^(?:(?:please|sorry|actually|correction|now|instead|and|but)\s+)*"
            r"(?:(?:set|change|update|make|use|apply|charge|increase|reduce|rename|correct)\s+)?"
            r"(?:to\s+)?(?:the\s+|a\s+)?",
            "",
            statement,
            flags=re.I,
        )
        if re.match(r"^invoice\s+", content, re.I) and not invoice_command_prefix(content):
            raise ValueError("invoice reference is not a preparation command")
        negative_context = _registration_facts(statement, statement)
        if re.fullmatch(r"(?:no\s+vat,?\s*)?not\s+registered", statement, re.I):
            negative_context = ""
        if _NEGATIVE.search(negative_context) and not re.match(r"^invoice\b", content, re.I):
            raise ValueError("unresolved negative statement")
        if re.match(
            r"^(?:amount\b|price\b|total\b|subtotal\b|grand\b|whole invoice\b|"
            r"labou?r\b|materials?\b|vat\b|"
            r"including\b|excluding\b|inclusive\b|exclusive\b|before\b|plus\b|"
            r"no\s+vat\b|not\s+(?:vat\s+)?registered\b|"
            r"replace\s+(?:all|the\s+(?:whole|entire))\b|"
            r"(?:it|that)(?:['’]?s|\s+is|\s+to)?\b|€|[0-9]|eur(?:os?)?)",
            content,
            re.I,
        ):
            if not _operational_words_supported(statement, item_names) or re.match(
                r"^[0-9]+\s+(?:invoice|job|bill)\s*$", statement, re.I
            ):
                raise ValueError("unsupported operational statement")
            continue
        if re.match(r"^(?:invoice|for)\s+", content, re.I):
            captured = _captured_invoice_statement(content, text_values)
            if captured != content and _operational_words_supported(captured, item_names):
                continue
        if re.match(r"^invoice\s+", content, re.I):
            if re.fullmatch(
                r"invoice\s+[^\W\d_][\w '’&/-]{0,100}\s+at\s+(?:No\.\s*)?"
                r"[0-9]+\s+[\w '’/-]{1,100}\s+for\s*(?:€|EUR|euros?)?\s*[0-9.,]+",
                content,
                re.I,
            ):
                continue
            tail = re.sub(r"^invoice\s+[^€0-9]+(?=€|[0-9])", "", content, flags=re.I)
            if tail != content and _operational_words_supported(tail, item_names):
                continue
        if re.fullmatch(r"for the estimate", statement, re.I):
            continue
        if any(
            re.fullmatch(
                r"for\s+[^:]+:\s*(?:supply|repair|replace|install)\s+" + re.escape(name),
                content,
                re.I,
            )
            for name in item_names
        ):
            continue
        if _document_scope(content) == DocumentScope.CURRENT and re.match(
            r"^(?:for\s+)?(?:this|current|new|the\s+(?:current|new)|the\s+invoice)\b", content, re.I
        ):
            if _operational_words_supported(statement, item_names):
                continue
            if any(
                re.fullmatch(
                    r"(?:this|the\s+(?:current|new))\s+(?:invoice|bill)\s+(?:is\s+)?for\s+"
                    + re.escape(value),
                    statement,
                    re.I,
                )
                for value in text_values
            ):
                continue
        if any(
            re.match(re.escape(name) + r"(?!\w)", content, re.I) for name in item_names
        ) and _operational_words_supported(statement, item_names):
            continue
        raise ValueError("unresolved statement in preparation request")


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
            or bool(re.fullmatch(r"\s*for\s+[^;:,\n!?]+[:,]\s*", prefix, re.I))
            or (
                not message[context.clause_start : start].strip()
                and not message[end : context.clause_end].strip(" .!?:\n")
                and allow_bare
                and not message[:start].strip()
                and not message[end:].strip(" .!?:\n")
                and re.match(
                    r"(?:fixing|repairing|repairs?|replacing|installing|installation|"
                    r"fitting|painting|tiling|servicing|service|maintenance|cleaning|"
                    r"cutting|building|skimming|laying|jetting|changing|welding|checking)\b",
                    message[start:end],
                    re.I,
                )
                is not None
                and not _NEGATIVE.search(message[start:end])
                and not _CONDITIONAL.search(message[start:end])
                and not _AMBIGUOUS.search(message[start:end])
                and not re.search(
                    r"\b(?:was|were|had|used|while|until|pending|awaiting|before|after)\b",
                    message[start:end],
                    re.I,
                )
                and not _SOFT_BOUNDARY.search(message[start:end])
                and not _HARD_BOUNDARY.search(message[start:end].rstrip(".!?"))
            )
        )
    return False


def item_description_evidence(
    description: str, value: str, evidence: str, message: str, *, within: str
) -> bool:
    """Bind a rename to a complete command and its original assertion context."""
    if re.search(r"\bor\b|\bversus\b|\bvs\.?\b", value, re.I):
        return False
    selector = re.escape(description)
    command = re.fullmatch(
        r"\s*(?:(?:please|actually|now|instead)\s+)*"
        rf"(?:rename\s+(?:the\s+)?{selector}|"
        rf"(?:change|set|update)\s+(?:the\s+)?"
        rf"(?:description\s+of\s+{selector}|{selector}\s+description))"
        r"\s+to\s+(?P<value>" + re.escape(value) + r")\s*",
        within,
        re.I,
    )
    if command is None:
        return False
    candidates = []
    for source in re.finditer(re.escape(within), message):
        start, end = (source.start() + offset for offset in command.span("value"))
        context = assertion_context(message, start, end, topic="text")
        if (
            context.intent == AssertionIntent.AFFIRMATIVE
            and context.document_scope == DocumentScope.CURRENT
        ):
            candidates.append((start, end))
    spans = [match.span() for match in re.finditer(re.escape(evidence), message)]
    return bool(spans) and all(
        any(left <= start and end <= right for start, end in candidates) for left, right in spans
    )


def text_evidence(
    field: TextField, value: str, evidence: str, message: str, *, allow_bare: bool = False
) -> bool:
    """A text value retains source role, polarity, document scope and conflicts."""
    # A model cannot extend a text field across an independent instruction and
    # also reuse that instruction as financial authority. Preserve only bounded
    # contact-data continuations; other multi-clause values need clarification.
    parts = re.split(r"[;\n!?]|(?<!\bNo)\.(?=\s|$)", value.rstrip(".!?"), flags=re.I)
    if any(
        not (
            field == "customer_details"
            and _contact_data_fragment(part.strip(), (";" + part.strip(),))
            or field == "work_description"
            and re.fullmatch(r"call\s+[\s+()0-9-]+", part.strip(), re.I) is not None
        )
        for part in parts[1:]
    ):
        return False
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
