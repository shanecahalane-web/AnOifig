"""Untrusted model contracts and deterministic invoice-note validation."""

import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Intent(StrEnum):
    GENERAL = "general"
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


class ProposedNotes(StrictModel):
    """The sole permitted tool: propose changes, never write or issue invoices."""

    intent: Literal["invoice_preparation", "customer_information", "correction"]
    changes: list[NoteChange] = Field(max_length=12)
    line_items: Annotated[list[LineItem], Field(min_length=1, max_length=20)] | None
    line_items_evidence: Annotated[str, Field(min_length=1, max_length=4096)] | None


class Reply(StrictModel):
    intent: Intent
    text: str = Field(min_length=1, max_length=700, pattern=r"\S")


class Decision(StrictModel):
    reply: Reply | None = None
    proposal: ProposedNotes | None = None


def numeric_evidence(value: str, evidence: str) -> bool:
    """Compare complete decimal tokens; 500 cannot be grounded in 1500 or -500."""
    if re.search(r"[£$]|\b(?:GBP|USD)\b", evidence, re.IGNORECASE):
        return False
    # Familiar shorthand is expanded deterministically, never by model arithmetic.
    normalised = re.sub(r"(?<=[0-9])[xX×](?=[0-9])", " x ", evidence)
    tokens = re.findall(
        r"(?<![\w.,])([+-]?[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)(k)?"
        r"(?:euros?|eur|e)?(?![\w]|[.,][0-9])",
        normalised,
        re.IGNORECASE,
    )
    return any(
        Decimal(token.replace(",", "")) * (1000 if suffix else 1) == money(value)
        for token, suffix in tokens
    )


def vat_evidence(value: str, evidence: str) -> bool:
    patterns = {
        "no_vat": r"\b(?:no vat|not (?:vat )?registered|vat exempt)\b",
        "inclusive": r"\b(?:including|inclusive|incl\.?|inc\.?|vat included)\b",
        "exclusive": r"\b(?:before|excluding|exclusive|excl\.?|ex|plus)\b",
    }
    if value not in patterns:
        return False
    if value == "inclusive" and re.search(
        r"\bnot\s+(?:including|inclusive|incl|inc)\b", evidence, re.I
    ):
        return False
    return re.search(patterns[value], evidence, re.IGNORECASE) is not None


def apply_proposal(notes: InvoiceNotes, proposal: ProposedNotes, message: str) -> InvoiceNotes:
    values = notes.model_dump()
    seen: set[str] = set()
    for change in proposal.changes:
        if change.field in seen or change.evidence not in message:
            raise ValueError("ungrounded or repeated change")
        seen.add(change.field)
        if change.field in {"amount", "labour", "materials", "vat_rate"}:
            if not numeric_evidence(change.value, change.evidence):
                raise ValueError("ungrounded amount")
        elif change.field == "vat_basis":
            if not vat_evidence(change.value, change.evidence):
                raise ValueError("ungrounded VAT basis")
        elif change.value.casefold() not in change.evidence.casefold():
            raise ValueError("ungrounded text")
        values[change.field] = change.value
    if proposal.line_items is not None:
        evidence = proposal.line_items_evidence
        if not evidence or evidence not in message:
            raise ValueError("ungrounded line items")
        for item in proposal.line_items:
            if (
                item.description.casefold() not in evidence.casefold()
                or not numeric_evidence(item.quantity, evidence)
                or not numeric_evidence(item.unit_price, evidence)
                or money(item.quantity) * money(item.unit_price) > Decimal("1000000")
            ):
                raise ValueError("invalid line item")
        values["line_items"] = [item.model_dump() for item in proposal.line_items]
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
    return (
        prefix + f"The information for {notes.customer_name} is saved for preparation. "
        "You can correct or add details. I haven't created or sent an invoice."
    )
