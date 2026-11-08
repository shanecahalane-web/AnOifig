"""Adjacent source-role and quoted-authority cases retained after first baseline."""

import pytest
from test_tara_review_authority import item_patch, proposed, reject, saved

from anoifig.tara.schemas import apply_proposal


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Price 3 valves.", "amount", "3"),
        ("Materials cost 3 valves.", "materials", "3"),
        ("Invoice reference EUR 500.", "amount", "500"),
        ("Reference number: EUR 500.", "amount", "500"),
        ("The address is EUR 25 Main Street.", "amount", "25"),
        ("Labour €8 per hour.", "labour", "8"),
        ("Materials price €200.", "amount", "200"),
        ("Materials amount €200.", "amount", "200"),
        ("Materials subtotal €200.", "amount", "200"),
        ("Labour total €500.", "amount", "500"),
        ("Total labour €500.", "amount", "500"),
    ],
)
def test_charge_role_does_not_erase_reference_count_rate_or_specific_field(message, field, value):
    reject(saved(), proposed((field, value, value)), message)


def test_an_hourly_rate_cannot_supply_an_items_unit_price():
    message = "Change valves unit price €8 per hour."
    reject(saved(items=True), proposed(patches=[item_patch(message, "8")]), message)


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Materials price €200.", "materials", "200"),
        ("Materials amount €200.", "materials", "200"),
        ("Materials subtotal €200.", "materials", "200"),
        ("Materials cost €200.", "materials", "200"),
        ("Labour total €500.", "labour", "500"),
        ("Total labour €500.", "labour", "500"),
        ("€500 for labour.", "labour", "500"),
        ("Price €3.", "amount", "3"),
        ("Labour 500.", "labour", "500"),
    ],
)
def test_specific_charge_labels_keep_their_supported_field_authority(message, field, value):
    original = saved()
    updated = apply_proposal(original, proposed((field, value, message)), message)
    assert updated.model_dump() == {**original.model_dump(), field: value}


@pytest.mark.parametrize("quote", ['"', "'", "“"])
def test_temporal_words_quoted_from_an_old_invoice_do_not_supply_current_authority(quote):
    close = "”" if quote == "“" else quote
    message = f"The old invoice says {quote}now use VAT 23%{close}."
    reject(saved(vat=True), proposed(("vat_rate", "23", "23%")), message)


@pytest.mark.parametrize(
    "message,field,value",
    [
        (
            "Set work description customer requested repairs.",
            "work_description",
            "customer requested repairs",
        ),
        ("Set customer name Customer Care Limited.", "customer_name", "Customer Care Limited"),
    ],
)
def test_field_words_inside_supplied_text_remain_data(message, field, value):
    original = saved()
    updated = apply_proposal(original, proposed((field, value, value)), message)
    assert updated.model_dump() == {**original.model_dump(), field: value}


def test_implicit_current_invoice_customers_cannot_contradict_each_other():
    message = "Invoice John for repairs; invoice Mary for repairs."
    reject(saved(items=True), proposed(("customer_name", "John", "John")), message)


def test_other_item_preservation_with_document_reference_does_not_cancel_selected_item():
    evidence = "Change valves unit price €30 each"
    message = evidence + "; leave elbows unchanged on this invoice."
    original = saved(items=True)
    updated = apply_proposal(
        original,
        proposed(patches=[item_patch(evidence)]),
        message,
        expected_version=7,
        current_version=7,
    )
    expected = original.model_dump()
    expected["line_items"][0]["unit_price"] = "30"
    assert updated.model_dump() == expected


@pytest.mark.parametrize(
    "field,value,assertion",
    [
        ("vat_rate", "23", "VAT 23%"),
        ("vat_basis", "inclusive", "including VAT"),
    ],
)
def test_question_punctuation_retains_heading_intent_without_an_interrogative_word(
    field, value, assertion
):
    message = "VAT on this invoice?\n- " + assertion
    reject(saved(vat=True), proposed((field, value, assertion)), message)
