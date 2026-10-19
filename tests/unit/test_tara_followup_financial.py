"""Remaining full-source currency annotations and non-assertive VAT language."""

import pytest

from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal


def change(field, value, evidence):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [{"field": field, "value": value, "evidence": evidence}],
            "line_items": None,
            "line_items_evidence": None,
        }
    )


@pytest.mark.parametrize("field", ["amount", "labour", "materials"])
@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize(
    "expression",
    [
        "500 in USD",
        "500 (USD)",
        "USD amount 500",
        "500 in $",
        "500 in usd",
        "500 (sek)",
        "sek amount 500",
        "500 (kr) in SEK",
    ],
)
def test_currency_annotation_cannot_be_removed_from_a_scalar_expression(field, cropped, expression):
    message = f"Change {field}: {expression}."
    original = InvoiceNotes(amount="450", labour="100", materials="350")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, change(field, "500", "500" if cropped else message), message)
    assert original.model_dump() == before


@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize(
    "message,field,value,evidence",
    [
        ("VAT 23% is incorrect.", "vat_rate", "23", "23%"),
        ("VAT 23% is wrong.", "vat_rate", "23", "23%"),
        ("VAT included is wrong.", "vat_basis", "inclusive", "VAT included"),
        ("Is VAT 23% correct?", "vat_rate", "23", "23%"),
        ("Is this including VAT?", "vat_basis", "inclusive", "including VAT"),
        ("VAT 23%?", "vat_rate", "23", "23%"),
        ("Including VAT?", "vat_basis", "inclusive", "Including VAT"),
        ("Should I use VAT 23%", "vat_rate", "23", "23%"),
        ("VAT 23% isn't correct.", "vat_rate", "23", "23%"),
        ("VAT included isn't right.", "vat_basis", "inclusive", "VAT included"),
    ],
)
def test_vat_questions_and_rejected_assertions_preserve_previous_facts(
    cropped, message, field, value, evidence
):
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, change(field, value, evidence if cropped else message), message)
    assert original.model_dump() == before


@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize(
    "message,field,value,evidence",
    [
        ("VAT 23% doesn't apply.", "vat_rate", "23", "23%"),
        ("VAT 23% shouldn't be used.", "vat_rate", "23", "23%"),
        ("VAT 23% cannot apply.", "vat_rate", "23", "23%"),
        ("VAT 23% can’t apply.", "vat_rate", "23", "23%"),
        ("VAT included doesn't apply.", "vat_basis", "inclusive", "VAT included"),
        ("VAT included shouldn't be used.", "vat_basis", "inclusive", "VAT included"),
        ("VAT included cannot apply.", "vat_basis", "inclusive", "VAT included"),
        ("The amount can't be €500.", "amount", "500", "500"),
        ("Labour shouldn’t be €500.", "labour", "500", "500"),
        ("Materials won't be €500.", "materials", "500", "500"),
    ],
)
def test_explicit_contracted_financial_negatives_preserve_notes(
    cropped, message, field, value, evidence
):
    original = InvoiceNotes(
        amount="450", labour="100", materials="350", vat_basis="exclusive", vat_rate="13.5"
    )
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, change(field, value, evidence if cropped else message), message)
    assert original.model_dump() == before


@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize(
    "message,field,value,evidence",
    [
        ("What does VAT 23% mean", "vat_rate", "23", "23%"),
        ("Which VAT rate 23% applies", "vat_rate", "23", "23%"),
        ("How is VAT included", "vat_basis", "inclusive", "VAT included"),
    ],
)
def test_vat_interrogative_heads_require_clarification_without_question_marks(
    cropped, message, field, value, evidence
):
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, change(field, value, evidence if cropped else message), message)
    assert original.model_dump() == before


@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize(
    "message,field,value,evidence",
    [
        ("VAT 23%, is that correct?", "vat_rate", "23", "23%"),
        ("VAT included, is that correct?", "vat_basis", "inclusive", "VAT included"),
        ("VAT 23%, incorrect.", "vat_rate", "23", "23%"),
        ("VAT 23% and is that correct?", "vat_rate", "23", "23%"),
        ("VAT included but that is wrong.", "vat_basis", "inclusive", "VAT included"),
        ("The amount €500 is incorrect.", "amount", "500", "500"),
        ("Charge €500, is that correct?", "amount", "500", "500"),
        ("Labour €500, incorrect.", "labour", "500", "500"),
    ],
)
def test_soft_continuations_cannot_hide_a_financial_question_or_rejection(
    cropped, message, field, value, evidence
):
    original = InvoiceNotes(
        amount="450", labour="100", materials="350", vat_basis="exclusive", vat_rate="13.5"
    )
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, change(field, value, evidence if cropped else message), message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("VAT 23%. Is the repair complete?", "vat_rate", "23"),
        ("VAT included. Is the repair complete?", "vat_basis", "inclusive"),
        ("VAT 23%; is the repair complete?", "vat_rate", "23"),
        ("VAT 23%. The old part is incorrect.", "vat_rate", "23"),
        ("VAT included, and that is correct.", "vat_basis", "inclusive"),
        ("VAT 23%, labour €500.", "vat_rate", "23"),
        ("Charge €500 for repairs to the wrong valve.", "amount", "500"),
        ("Charge €500. Is the repair complete?", "amount", "500"),
    ],
)
def test_positive_financial_assertions_keep_unrelated_sentence_context(message, field, value):
    assert (
        getattr(apply_proposal(InvoiceNotes(), change(field, value, message), message), field)
        == value
    )


@pytest.mark.parametrize(
    "message",
    [
        "Invoice Seán €500 for repairs.",
        "Charge €500 for all labour.",
        "Charge €500 for a new pen tray.",
        "Charge 500 (EUR).",
        "The amount in EUR is 500.",
    ],
)
def test_supported_amounts_keep_names_and_ordinary_words(message):
    assert apply_proposal(InvoiceNotes(), change("amount", "500", message), message).amount == "500"


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("VAT 23% is correct.", "vat_rate", "23"),
        ("VAT included is correct.", "vat_basis", "inclusive"),
        ("No VAT, not registered.", "vat_basis", "no_vat"),
        ("Use VAT 13.5% for repairs to the wrong valve.", "vat_rate", "13.5"),
    ],
)
def test_positive_vat_assertions_remain_supported(message, field, value):
    assert (
        getattr(apply_proposal(InvoiceNotes(), change(field, value, message), message), field)
        == value
    )
