"""Financial evidence retains total scope and current VAT choices."""

import pytest

from anoifig.tara.financial import item_clauses, line_total_matches, unit_price_evidence
from anoifig.tara.schemas import (
    InvoiceNotes,
    ProposedNotes,
    _vat_rate_evidence,
    apply_proposal,
    vat_evidence,
)

ITEMS = [
    {"description": "valves", "quantity": "3", "unit_price": "25"},
    {"description": "elbows", "quantity": "2", "unit_price": "10"},
]
INVOICE_TOTALS = [
    "overall invoice total",
    "invoice total",
    "grand total",
    "total for the invoice",
    "invoice subtotal",
    "overall total",
    "total for all items",
    "whole bill total",
    "invoice amount",
    "whole invoice price",
    "price for the entire invoice",
    "grand cost",
]
VAT_CHOICES = [
    "VAT options:\nVAT 23%",
    "Choose VAT treatment:\nVAT 23%",
    "Which VAT treatment applies?\nVAT 23%",
    "VAT options:\nVAT 23%\nexcluding VAT",
    "VAT options:\nVAT exempt\nVAT 23%",
    "Choose VAT treatment:\nVAT exempt\nVAT 23%",
    "Either:\nVAT exempt\nVAT 23%",
    "VAT 23%\nVAT exempt",
    "VAT exempt\nVAT 23%",
    "VAT 23%; VAT exempt",
    "VAT 23%\nNo VAT",
    "VAT 23%; No VAT",
    "VAT 23%\nZero-rated",
    "VAT options:\n- Zero-rated\n- VAT 23%",
    "VAT options:\nVAT exempt\n\nVAT 23%",
    "VAT 23%; including VAT; VAT exempt",
]


def proposed(**values):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [],
            "line_items": None,
            "line_items_evidence": None,
            **values,
        }
    )


def saved():
    return InvoiceNotes(vat_basis="exclusive", vat_rate="13.5", line_items=ITEMS)


def patch(message, value="30", *, evidence=None, field="unit_price"):
    return proposed(
        line_item_patches=[
            {
                "index": 0,
                "description": "valves",
                "evidence": message,
                "changes": [{"field": field, "value": value, "evidence": evidence or message}],
            }
        ]
    )


@pytest.mark.parametrize("label", INVOICE_TOTALS)
def test_invoice_total_is_not_a_line_product(label):
    message = f"Change valves so the {label} is €90."
    context = item_clauses(message, "valves")[0].text
    # No assertion that a line product equals a wider total is permitted.
    assert not unit_price_evidence(
        "30",
        message,
        message,
        quantity="3",
        within=context,
        item_description="valves",
        allow_existing_quantity=True,
    )
    # Literal matching must not launder the invoice amount into a unit price.
    assert not unit_price_evidence(
        "90",
        message,
        message,
        quantity="3",
        within=context,
        item_description="valves",
        allow_existing_quantity=True,
    )


@pytest.mark.parametrize("label", INVOICE_TOTALS)
@pytest.mark.parametrize("cropped", [False, True])
def test_invoice_total_correction_preserves_all_saved_values(label, cropped):
    message = f"Change valves so the {label} is €90."
    original = saved()
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(
            original,
            patch(message, evidence="€90" if cropped else None),
            message,
            expected_version=4,
            current_version=4,
        )
    assert original.model_dump() == before


@pytest.mark.parametrize("label", INVOICE_TOTALS)
def test_initial_items_cannot_derive_a_price_from_an_invoice_total(label):
    message = f"3 valves for an {label} of €90 and 2 elbows at €10."
    items = [{**ITEMS[0], "unit_price": "30"}, ITEMS[1]]
    original = InvoiceNotes(vat_basis="no_vat")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, proposed(line_items=items, line_items_evidence=message), message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "suffix",
    [
        "; invoice total €90",
        "\ngrand total €90",
        "; total for all items €90",
        "; invoice total €95; invoice total €90",
        "; invoice total €95.001",
        "; overall price €90",
        "\noverall cost €90",
    ],
)
def test_separate_or_cropped_invoice_totals_cannot_be_discarded(suffix):
    message = "Make valves unit price €30 each" + suffix
    original = InvoiceNotes(vat_basis="no_vat", line_items=ITEMS)
    evidence = "Make valves unit price €30 each"
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, patch(evidence), message, expected_version=4, current_version=4)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message",
    [
        "Make valves total price €90",
        "Make valves line subtotal €90",
        "Make valves unit price €30 each total €90",
    ],
)
def test_item_totals_still_validate_exact_products(message):
    context = item_clauses(message, "valves")[0].text
    assert line_total_matches("3", "30", message, within=context, item_description="valves")
    original = saved()
    result = apply_proposal(
        original, patch(message), message, expected_version=4, current_version=4
    )
    assert result.model_dump() == {
        **original.model_dump(),
        "line_items": [{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
    }


@pytest.mark.parametrize("total,accepted", [("110", True), ("90", False)])
def test_stated_unit_price_and_invoice_total_use_the_complete_item_list(total, accepted):
    message = f"Make valves unit price €30 each; invoice total €{total}"
    original = InvoiceNotes(vat_basis="no_vat", line_items=ITEMS)
    proposal = patch("Make valves unit price €30 each")
    if not accepted:
        with pytest.raises(ValueError):
            apply_proposal(original, proposal, message, expected_version=4, current_version=4)
    else:
        updated = apply_proposal(original, proposal, message, expected_version=4, current_version=4)
        assert updated.model_dump() == {
            **original.model_dump(),
            "line_items": [{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
        }


def test_invoice_preparation_verb_does_not_change_an_explicit_items_total_scope():
    message = "Invoice John for 3 valves line total of €75"
    p = proposed(line_items=[ITEMS[0]], line_items_evidence=message)
    original = InvoiceNotes(vat_basis="no_vat")
    assert apply_proposal(original, p, message).line_items[0].model_dump() == ITEMS[0]


@pytest.mark.parametrize(
    "message",
    [
        "3 valves at €25 each invoice total €75",
        "3 valves unit price €25 grand total €75",
    ],
)
def test_a_following_invoice_label_cannot_change_a_stated_units_role(message):
    p = proposed(line_items=[ITEMS[0]], line_items_evidence=message)
    original = InvoiceNotes(vat_basis="no_vat")
    assert apply_proposal(original, p, message).model_dump() == {
        **original.model_dump(),
        "line_items": [ITEMS[0]],
    }


@pytest.mark.parametrize("message", VAT_CHOICES)
@pytest.mark.parametrize("cropped", [False, True])
def test_formatted_vat_rate_choices_preserve_both_fields(message, cropped):
    assert not _vat_rate_evidence("23", "23%" if cropped else message, message, None)
    original = saved()
    before = original.model_dump()
    p = proposed(
        changes=[{"field": "vat_rate", "value": "23", "evidence": "23%" if cropped else message}]
    )
    with pytest.raises(ValueError):
        apply_proposal(original, p, message)
    assert original.model_dump() == before


@pytest.mark.parametrize("message", [m for m in VAT_CHOICES if "exempt" in m or "No VAT" in m])
def test_formatted_vat_choices_also_guard_basis_proposals(message):
    assert not vat_evidence("no_vat", message)
    original = saved()
    before = original.model_dump()
    evidence = "VAT exempt" if "VAT exempt" in message else "No VAT"
    p = proposed(changes=[{"field": "vat_basis", "value": "no_vat", "evidence": evidence}])
    with pytest.raises(ValueError):
        apply_proposal(original, p, message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message",
    [
        "VAT options:\nNo VAT\nZero-rated",
        "VAT options:\nVAT exempt\nZero-rated",
        "VAT 0%\nNo VAT",
        "VAT 0%; VAT exempt",
        "VAT 23%\nVAT 13.5%\nexcluding VAT",
        "VAT 23%\nincluding VAT\nexcluding VAT",
    ],
)
def test_conflicts_are_not_lost_via_an_intervening_compatible_assertion(message):
    original = saved()
    before = original.model_dump()
    field, value = ("vat_basis", "exclusive") if "excluding" in message else ("vat_basis", "no_vat")
    p = proposed(changes=[{"field": field, "value": value, "evidence": message}])
    with pytest.raises(ValueError):
        apply_proposal(original, p, message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Use VAT 23%\nexcluding VAT", "vat_rate", "23"),
        ("Use VAT 23%; excluding VAT", "vat_basis", "exclusive"),
        ("Use VAT 0%\nincluding VAT", "vat_rate", "0"),
        ("Use VAT 23%. The old job was exempt.", "vat_rate", "23"),
        ("Use VAT 23%; the previous invoice was exempt.", "vat_rate", "23"),
        ("Use VAT 23%. Choose repairs or replacement.", "vat_rate", "23"),
        ("VAT exempt.\nRepairs or installation are fine.", "vat_basis", "no_vat"),
        ("Use VAT 23%\nVAT 23%", "vat_rate", "23"),
        ("Use VAT 23%; discount 10%.", "vat_rate", "23"),
    ],
)
def test_compatible_affirmative_and_unrelated_statements_remain_supported(message, field, value):
    original = saved()
    p = proposed(changes=[{"field": field, "value": value, "evidence": message}])
    updated = apply_proposal(original, p, message)
    assert updated.model_dump() == {**original.model_dump(), field: value}
