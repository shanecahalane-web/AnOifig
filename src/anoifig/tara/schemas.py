"""Untrusted model contracts and deterministic invoice-note validation."""

import json
import re
import unicodedata
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from anoifig.tara.financial import (
    clauses,
    expression_context_safe,
    financial_negative_clause,
    inherited_negative,
    negative_clause,
    numeric_evidence,
)
from anoifig.tara.financial import (
    evidence_spans as _evidence_spans,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Intent(StrEnum):
    GENERAL = "general"
    CLARIFICATION = "clarification"
    INVOICE = "invoice_preparation"
    CUSTOMER = "customer_information"
    CORRECTION = "correction"
    FUNCTIONALITY = "functionality"
    UNSUPPORTED = "unsupported"


Money = Annotated[str, Field(max_length=16, pattern=r"^(0|[1-9][0-9]{0,6})(\.[0-9]{1,2})?$")]


def money(value: str) -> Decimal:
    if not re.fullmatch(r"(0|[1-9][0-9]{0,6})(\.[0-9]{1,2})?", value):
        raise ValueError("invalid monetary value")
    result = Decimal(value)
    if not Decimal("0") <= result <= Decimal("1000000"):
        raise ValueError("monetary value outside supported range")
    return result


class LineItem(StrictModel):
    description: str = Field(min_length=1, max_length=300, pattern=r"\S")
    quantity: Money
    unit_price: Money

    @field_validator("quantity", "unit_price")
    @classmethod
    def validate_number(cls, value: str) -> str:
        number = money(value)
        if number <= 0:
            raise ValueError("line quantities and prices must be positive")
        return value


class InvoiceNotes(StrictModel):
    customer_name: str | None = Field(default=None, min_length=1, max_length=200)
    work_description: str | None = Field(default=None, min_length=1, max_length=1000)
    amount: Money | None = None
    labour: Money | None = None
    materials: Money | None = None
    vat_basis: Literal["inclusive", "exclusive", "no_vat"] | None = None
    vat_rate: Money | None = None
    customer_details: str | None = Field(default=None, min_length=1, max_length=500)
    line_items: list[LineItem] = Field(default_factory=list, max_length=20)

    @field_validator("customer_name")
    @classmethod
    def customer_name_structure(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Names are single data labels, not paragraphs, URLs, instructions or
        # first-person statements. Preserve Unicode letters and business syntax.
        if (
            value != value.strip()
            or not any(char.isalpha() for char in value)
            or len(value.split()) > 24
            or any(
                not (unicodedata.category(char)[0] in {"L", "M", "N"} or char in " &'’.,()-/")
                for char in value
            )
            or re.search(r"\.(?:\s+[A-Za-z]{2,})", value)
            or re.match(r"(?:I|we|you|they)\s+", value, re.I)
            or re.match(r"(?:please|ignore|system|assistant)\b", value, re.I)
            or re.search(r"\b(?:is|are|was|were|have|has|had|must|should)\b", value, re.I)
        ):
            raise ValueError("invalid customer name structure")
        return value

    @field_validator("customer_name", "work_description", "customer_details")
    @classmethod
    def nonblank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("blank preparation detail")
        return value

    @field_validator("amount", "labour", "materials", "vat_rate")
    @classmethod
    def validate_money(cls, value: str | None) -> str | None:
        if value is not None:
            money(value)
        return value

    @field_validator("vat_rate")
    @classmethod
    def validate_rate(cls, value: str | None) -> str | None:
        if value is not None and money(value) > 100:
            raise ValueError("invalid percentage")
        return value


NoteField = Literal[
    "customer_name",
    "work_description",
    "amount",
    "labour",
    "materials",
    "vat_basis",
    "vat_rate",
    "customer_details",
]


class NoteChange(StrictModel):
    field: NoteField
    value: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=4096)


class LineItemChange(StrictModel):
    field: Literal["description", "quantity", "unit_price"]
    value: str = Field(min_length=1, max_length=300)
    evidence: str = Field(min_length=1, max_length=4096)


class LineItemPatch(StrictModel):
    """Select an existing item within the application-bound notes version."""

    index: int = Field(ge=0, lt=20)
    description: str = Field(min_length=1, max_length=300, pattern=r"\S")
    evidence: str = Field(min_length=1, max_length=4096)
    changes: list[LineItemChange] = Field(min_length=1, max_length=3)


class ProposedNotes(StrictModel):
    """The sole permitted tool: propose changes, never write or issue invoices."""

    intent: Literal["invoice_preparation", "customer_information", "correction"]
    changes: list[NoteChange] = Field(max_length=12)
    line_items: Annotated[list[LineItem], Field(min_length=1, max_length=20)] | None
    line_items_evidence: Annotated[str, Field(min_length=1, max_length=4096)] | None
    line_item_patches: list[LineItemPatch] = Field(default_factory=list, max_length=20)


class Reply(StrictModel):
    intent: Intent
    text: str = Field(min_length=1, max_length=700, pattern=r"\S")
    social_act: Literal["greeting", "thanks", "check_in", "acknowledgement", "help"] = "help"


class Decision(StrictModel):
    reply: Reply | None = None
    proposal: ProposedNotes | None = None


PendingClarification = Literal["vat_basis", "vat_rate"]


def vat_evidence(
    value: str, evidence: str, *, pending_clarification: PendingClarification | None = None
) -> bool:
    if not expression_context_safe(evidence, []):
        return False
    patterns = {
        "no_vat": r"\b(?:no vat|not vat registered|not registered (?:for )?vat|vat exempt)\b",
        "inclusive": r"\b(?:(?:including|inclusive(?: of)?|incl\.?|inc\.?)\s+vat|vat included)\b",
        "exclusive": r"\b(?:before|excluding|exclusive(?: of)?|excl\.?|ex|plus)\s+vat\b",
    }
    if value not in patterns:
        return False
    if re.search(
        r"\b(?:not|never)\s+(?:including|inclusive|incl|inc|excluding|exclusive|excl|before|plus)\b",
        evidence,
        re.I,
    ):
        return False
    if value == "no_vat" and re.search(
        r"\bno vat\s+(?:information|rate|details|number|registration|status)\b", evidence, re.I
    ):
        return False
    supported: set[str] = set()
    for basis, pattern in patterns.items():
        for match in re.finditer(pattern, evidence, re.I):
            clause = next(
                (
                    part
                    for part in clauses(evidence)
                    if part.start <= match.start() and match.end() <= part.end
                ),
                None,
            )
            if clause is None:
                return False
            assertion = evidence[clause.start : match.start()] + evidence[match.end() : clause.end]
            if (
                negative_clause(assertion)
                or inherited_negative(evidence, clause)
                or re.search(r"\bor\b", clause.text, re.I)
            ):
                return False
            supported.add(basis)
    if len(supported) > 1:
        return False
    if value in supported:
        return True
    if pending_clarification != "vat_basis":
        return False
    answers = {
        "no_vat": r"(?:no vat|not registered|not vat registered|vat exempt)",
        "inclusive": r"(?:including|inclusive|incl\.?|inc\.?)",
        "exclusive": r"(?:before|excluding|exclusive|excl\.?|ex|plus)",
    }
    return re.fullmatch(answers[value] + r"[.!]?", evidence.strip(), re.I) is not None


def _vat_rate_evidence(
    value: str,
    evidence: str,
    message: str,
    pending_clarification: PendingClarification | None,
) -> bool:
    if not numeric_evidence(value, evidence, message, allow_percentage=True):
        return False
    number = r"[0-9]+(?:\.[0-9]+)?"
    percent = r"(?:%|per\s*cent)"
    patterns = (
        rf"\bvat(?:\s+rate)?\s*(?:(?:is|at|of)\s+|:\s*)?(?P<rate>{number})\s*{percent}",
        rf"\bvat\s+rate\s*(?:(?:is|at|of)\s+|:\s*)?(?P<rate>{number})(?![\w.]|,[0-9])",
        rf"(?<![\w.,])(?P<rate>{number})\s*{percent}\s*(?:for\s+)?vat\b",
    )
    spans = _evidence_spans(message, evidence)
    rates: set[Decimal] = set()
    grounded = False
    for pattern in patterns:
        for match in re.finditer(pattern, message, re.I):
            start, end = match.span("rate")
            clause = next(
                (
                    part
                    for part in clauses(message)
                    if part.start <= match.start() and match.end() <= part.end
                ),
                None,
            )
            if (
                clause is None
                or negative_clause(clause.text)
                or inherited_negative(message, clause)
                or re.search(r"(?:€|\b(?:EUR|euros?))\s*$", message[:start], re.I)
                or re.match(rf"\s*(?:{percent}\s*)?(?:€|(?:EUR|euros?|e)\b)", message[end:], re.I)
                or re.search(r"\b(?:no|not|never)\s+(?:the\s+)?$", message[:start], re.I)
            ):
                return False
            rate = money(match.group("rate"))
            rates.add(rate)
            if rate == money(value) and any(
                left <= start and end <= right for left, right in spans
            ):
                grounded = True
    if rates:
        return grounded and len(rates) == 1
    # A short answer is meaningful only when the application asked this exact
    # missing question in the currently bound version of the notes.
    return (
        pending_clarification == "vat_rate"
        and re.fullmatch(rf"\s*{number}\s*(?:{percent})?\s*[.!]?\s*", message, re.I) is not None
    )


def _mentions(description: str, text: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(description) + r"(?!\w)", text, re.I) is not None


def _item_clauses(description: str, descriptions: list[str], message: str) -> list[str]:
    return [
        clause.text
        for clause in clauses(message)
        if _mentions(description, clause.text)
        and not financial_negative_clause(clause.text)
        and not inherited_negative(message, clause, financial=True)
        and not any(
            other.casefold() != description.casefold() and _mentions(other, clause.text)
            for other in descriptions
        )
    ]


def _patch_line_items(notes: InvoiceNotes, proposal: ProposedNotes, message: str) -> list[LineItem]:
    items = list(notes.line_items)
    selected: set[int] = set()
    for patch in proposal.line_item_patches:
        if patch.index in selected or patch.index >= len(notes.line_items):
            raise ValueError("invalid or repeated line item selection")
        selected.add(patch.index)
        item = notes.line_items[patch.index]
        if (
            patch.description.casefold() != item.description.casefold()
            or sum(
                x.description.casefold() == item.description.casefold() for x in notes.line_items
            )
            != 1
            or patch.evidence not in message
            or not _mentions(item.description, patch.evidence)
            or any(
                _mentions(other.description, patch.evidence)
                for index, other in enumerate(notes.line_items)
                if index != patch.index
            )
        ):
            raise ValueError("ambiguous or ungrounded line item selection")
        # A selector and all of its values must belong to one complete original
        # item clause. Model-selected evidence cannot bridge ';', conjunctions or
        # another item's preservation instruction.
        contexts = [
            clause
            for clause in _item_clauses(
                item.description, [entry.description for entry in notes.line_items], message
            )
            if patch.evidence.strip().rstrip(".!?;,") in clause
        ]
        if len(contexts) != 1:
            raise ValueError("ambiguous line item clause")
        context = contexts[0]
        values = item.model_dump()
        seen: set[str] = set()
        for change in patch.changes:
            if change.field in seen or change.evidence not in patch.evidence:
                raise ValueError("ungrounded or repeated line item change")
            seen.add(change.field)
            if change.field == "description":
                if not _mentions(change.value, change.evidence):
                    raise ValueError("ungrounded line item description")
            elif not numeric_evidence(
                change.value,
                change.evidence,
                message,
                within=context,
                role=change.field,
                item_description=item.description,
            ):
                raise ValueError("ungrounded line item amount")
            values[change.field] = change.value
        updated = LineItem.model_validate(values)
        if money(updated.quantity) * money(updated.unit_price) > Decimal("1000000"):
            raise ValueError("line item amount outside supported range")
        items[patch.index] = updated
    return items


def apply_proposal(
    notes: InvoiceNotes,
    proposal: ProposedNotes,
    message: str,
    *,
    pending_clarification: PendingClarification | None = None,
    expected_version: int | None = None,
    current_version: int | None = None,
) -> InvoiceNotes:
    if (expected_version is not None or current_version is not None) and (
        expected_version is None or current_version is None or expected_version != current_version
    ):
        raise ValueError("stale preparation notes")
    if proposal.line_item_patches and (
        expected_version is None or current_version is None or proposal.line_items is not None
    ):
        raise ValueError("line item patches require a single version-bound operation")
    values = notes.model_dump()
    seen: set[str] = set()
    for change in proposal.changes:
        if change.field in seen or change.evidence not in message:
            raise ValueError("ungrounded or repeated change")
        seen.add(change.field)
        if change.field in {"amount", "labour", "materials"}:
            if not numeric_evidence(change.value, change.evidence, message, role=change.field):
                raise ValueError("ungrounded amount")
        elif change.field == "vat_rate":
            if not _vat_rate_evidence(
                change.value, change.evidence, message, pending_clarification
            ):
                raise ValueError("ungrounded VAT rate")
        elif change.field == "vat_basis":
            # Validate the original clause, not a substring such as "including"
            # taken from "not including VAT".
            if not vat_evidence(
                change.value, message, pending_clarification=pending_clarification
            ) or not vat_evidence(
                change.value, change.evidence, pending_clarification=pending_clarification
            ):
                raise ValueError("ungrounded VAT basis")
        elif change.value.casefold() not in change.evidence.casefold():
            raise ValueError("ungrounded text")
        values[change.field] = change.value
    if proposal.line_items is not None:
        if (
            notes.line_items
            and re.match(
                r"\s*(?:please\s+)?replace\s+(?:all\s+(?:the\s+)?line\s+items|"
                r"the\s+(?:whole|entire)\s+(?:item|line item)\s+list)\s+(?:with\b|:)",
                message,
                re.I,
            )
            is None
        ):
            raise ValueError(
                "existing items require selective patches or explicit list replacement"
            )
        evidence = proposal.line_items_evidence
        if not evidence or evidence not in message:
            raise ValueError("ungrounded line items")
        for item in proposal.line_items:
            descriptions = [entry.description for entry in proposal.line_items]
            contexts = _item_clauses(item.description, descriptions, message)
            if (
                item.description.casefold() not in evidence.casefold()
                or sum(name.casefold() == item.description.casefold() for name in descriptions) != 1
                or not any(
                    numeric_evidence(
                        item.quantity,
                        evidence,
                        message,
                        within=context,
                        role="quantity",
                        item_description=item.description,
                    )
                    and numeric_evidence(
                        item.unit_price,
                        evidence,
                        message,
                        within=context,
                        role="unit_price",
                        item_description=item.description,
                    )
                    for context in contexts
                )
                or money(item.quantity) * money(item.unit_price) > Decimal("1000000")
            ):
                raise ValueError("invalid line item")
        values["line_items"] = [item.model_dump() for item in proposal.line_items]
    elif proposal.line_item_patches:
        values["line_items"] = [
            item.model_dump() for item in _patch_line_items(notes, proposal, message)
        ]
    return InvoiceNotes.model_validate(values)


def render_notes(notes: InvoiceNotes, *, correction: bool = False) -> str:
    prefix = "Updated that. " if correction else ""
    if not notes.customer_name:
        return prefix + "Who is the work for?"
    if not notes.work_description and not notes.line_items:
        return prefix + "What work should I include?"
    if (
        not any(value is not None for value in (notes.amount, notes.labour, notes.materials))
        and not notes.line_items
    ):
        return prefix + "What are the charges for the work and materials?"
    if notes.vat_basis is None:
        amount = f"€{notes.amount}" if notes.amount is not None else "those charges"
        return prefix + f"Is {amount} before or including VAT, or are you not VAT registered?"
    if notes.vat_basis != "no_vat" and notes.vat_rate is None:
        return prefix + "What VAT rate applies? I won't assume a rate."
    # Display a validated label separately from application status. Revalidate
    # here as well so legacy/unvalidated objects cannot turn a name into prose.
    try:
        customer = InvoiceNotes(customer_name=notes.customer_name).customer_name
    except ValueError:
        customer = None
    label = (
        "Customer name (provided): " + json.dumps(customer, ensure_ascii=False) + "\n"
        if customer is not None
        else ""
    )
    return (
        label + prefix + "The information is saved for preparation. "
        "You can correct or add details. I haven't created or sent an invoice."
    )
