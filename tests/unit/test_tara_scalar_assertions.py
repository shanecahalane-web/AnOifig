"""Scalar charges retain whole-message statement intent and document identity."""

import pytest

from anoifig.tara.financial import numeric_evidence
from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal


def scalar(field, message, *, cropped=False):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [
                {"field": field, "value": "500", "evidence": "500" if cropped else message}
            ],
            "line_items": None,
            "line_items_evidence": None,
        }
    )


@pytest.mark.parametrize("field", ["amount", "labour", "materials"])
@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize(
    "template",
    [
        "Which {field} applies?\n- €500",
        "Which {field} applies?\n1. €500",
        "Which {field} applies?\n(a) €500",
        "Which {field} applies?; - €500",
        "Financial options:\n- €500",
        "Choose one:\n(a) €500",
        "The old invoice {field} €500",
    ],
)
def test_nonassertive_or_historical_scalar_cannot_replace_current_charges(field, cropped, template):
    message = template.format(field=field)
    evidence = "500" if cropped else message
    original = InvoiceNotes(amount="450", labour="100", materials="350")
    before = original.model_dump()
    assert not numeric_evidence("500", evidence, message, role=field)
    with pytest.raises(ValueError):
        apply_proposal(original, scalar(field, message, cropped=cropped), message)
    assert original.model_dump() == before


@pytest.mark.parametrize("field", ["amount", "labour", "materials"])
@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize(
    "template",
    [
        "Set {field} €500; no VAT.",
        "Charge {field} €500, not VAT registered.",
        "Set {field} €500; is the repair complete?",
        "No VAT; set {field} €500.",
    ],
)
def test_current_affirmative_scalar_survives_independent_registration_or_question(
    field, cropped, template
):
    message = template.format(field=field)
    original = InvoiceNotes(amount="450", labour="100", materials="350")
    updated = apply_proposal(original, scalar(field, message, cropped=cropped), message)
    assert updated.model_dump() == {**original.model_dump(), field: "500"}


@pytest.mark.parametrize("field", ["amount", "labour", "materials"])
@pytest.mark.parametrize(
    "template",
    [
        "Deposit €500",
        "Set {field} deposit €500",
        "Set {field} unit price €500",
        "Set {field} €500 each",
        "Set {field} price per unit €500",
    ],
)
def test_explicit_unit_or_partial_scope_cannot_be_widened_to_a_scalar_charge(field, template):
    message = template.format(field=field)
    original = InvoiceNotes(amount="450", labour="100", materials="350")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, scalar(field, message, cropped=True), message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "field,message",
    [
        ("labour", "Labour €500 deposit €25"),
        ("materials", "Materials €500 unit price €25"),
        ("amount", "Amount €500 deposit €25"),
    ],
)
def test_a_following_amounts_label_does_not_change_the_preceding_scalar(field, message):
    original = InvoiceNotes(amount="450", labour="100", materials="350")
    updated = apply_proposal(original, scalar(field, message, cropped=True), message)
    assert updated.model_dump() == {**original.model_dump(), field: "500"}
