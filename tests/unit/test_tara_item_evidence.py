"""Item totals, prices and quantities retain their original financial roles."""

import pytest

from anoifig.tara.financial import numeric_evidence
from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal


def item_proposal(message, *, quantity="3", price="75", description="valves"):
    return ProposedNotes.model_validate(
        {
            "intent": "invoice_preparation",
            "changes": [],
            "line_items": [{"description": description, "quantity": quantity, "unit_price": price}],
            "line_items_evidence": message,
        }
    )


def saved_items():
    return InvoiceNotes.model_validate(
        {
            "customer_name": "John",
            "vat_basis": "exclusive",
            "vat_rate": "13.5",
            "line_items": [
                {"description": "valves", "quantity": "3", "unit_price": "25"},
                {"description": "elbows", "quantity": "2", "unit_price": "10"},
            ],
        }
    )


def patch(message, *, value="75", evidence=None, quantity=None):
    changes = [{"field": "unit_price", "value": value, "evidence": evidence or message}]
    if quantity is not None:
        changes.append({"field": "quantity", "value": quantity, "evidence": message})
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [],
            "line_items": None,
            "line_items_evidence": None,
            "line_item_patches": [
                {"index": 0, "description": "valves", "evidence": message, "changes": changes}
            ],
        }
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "for a total price of €75",
        "total cost €75",
        "subtotal price €75",
        "overall cost at €75",
        "deposit price €75",
        "at a total of €75",
        "€75 total",
        "at €75 overall",
        "price €75 subtotal",
    ],
)
@pytest.mark.parametrize("cropped", [False, True])
def test_total_cannot_be_laundered_into_a_unit_price(phrase, cropped):
    message = f"3 valves {phrase}"
    evidence = "75" if cropped else message
    assert not numeric_evidence(
        "75", evidence, message, role="unit_price", item_description="valves"
    )
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, item_proposal(message), message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message",
    [
        "Make valves total price €75",
        "Make valves subtotal cost €75",
        "Make valves overall price at €75",
        "Make valves price €75 total",
        "Make valves deposit cost €75",
    ],
)
def test_total_correction_preserves_current_unit_price_and_other_item(message):
    original = saved_items()
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, patch(message), message, expected_version=7, current_version=7)
    assert original.model_dump() == before


@pytest.mark.parametrize("marker", ["each", "apiece", "per unit", "per item", "per-unit"])
def test_explicit_unit_price_controls_remain_supported(marker):
    message = f"3 valves at €25 {marker}"
    updated = apply_proposal(InvoiceNotes(), item_proposal(message, price="25"), message)
    assert updated.line_items[0].model_dump() == {
        "description": "valves",
        "quantity": "3",
        "unit_price": "25",
    }


@pytest.mark.parametrize(
    "message,price",
    [
        ("3 valves for a total price of €75", "25"),
        ("3 valves total cost €75", "25"),
        ("4 valves subtotal €101", "25.25"),
        ("2 valves overall price €50.50", "25.25"),
        ("3 valves at €25 each total €75", "25"),
    ],
)
def test_exact_quantity_times_unit_price_may_validate_a_bound_total(message, price):
    quantity = message.split()[0]
    updated = apply_proposal(
        InvoiceNotes(), item_proposal(message, quantity=quantity, price=price), message
    )
    assert updated.line_items[0].model_dump() == {
        "description": "valves",
        "quantity": quantity,
        "unit_price": price,
    }


@pytest.mark.parametrize(
    "message,price",
    [
        ("3 valves total price €100", "33.33"),
        ("3 valves total price €100", "33.34"),
        ("3 valves total price €75", "75"),
        ("3 valves deposit €75", "25"),
        ("3 valves total €75 or €90", "25"),
        ("3 valves total £75", "25"),
        ("3 valves total -€75", "25"),
        ("3 valves total €75 each", "25"),
        ("3 valves at €25 each total €90", "25"),
        ("3 valves total €75 for 2 items", "25"),
    ],
)
def test_total_derivation_cannot_round_or_discard_conflicting_evidence(message, price):
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, item_proposal(message, price=price), message)
    assert original.model_dump() == before


def test_exact_total_correction_uses_version_bound_quantity_and_preserves_other_data():
    original = saved_items()
    before = original.model_dump()
    message = "Make valves total price €90"
    updated = apply_proposal(
        original, patch(message, value="30"), message, expected_version=7, current_version=7
    )
    expected = before.copy()
    expected["line_items"] = [
        {"description": "valves", "quantity": "3", "unit_price": "30"},
        {"description": "elbows", "quantity": "2", "unit_price": "10"},
    ]
    assert updated.model_dump() == expected
    assert original.model_dump() == before


@pytest.mark.parametrize("separator", ["with", "plus", "&", "and", ";", ","])
@pytest.mark.parametrize("first,second", [("€25", "10"), ("25", "€10"), ("25", "10")])
def test_initial_item_cannot_borrow_an_omitted_items_unmarked_price(separator, first, second):
    message = f"3 valves at {first} {separator} elbows at {second}"
    assert not numeric_evidence(
        "10", message, message, role="unit_price", item_description="valves"
    )
    with pytest.raises(ValueError):
        apply_proposal(InvoiceNotes(), item_proposal(message, price="10"), message)


@pytest.mark.parametrize("separator", ["with", "plus", "&", "and", ";", ","])
def test_selected_price_correction_cannot_borrow_another_items_value(separator):
    message = f"Make valves at €30 {separator} elbows at 40"
    original = saved_items()
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(
            original, patch(message, value="40"), message, expected_version=7, current_version=7
        )
    assert original.model_dump() == before


@pytest.mark.parametrize("separator", ["with", "plus", "&", "and", ";", ","])
def test_multi_item_clauses_keep_each_price_and_quantity(separator):
    message = f"3 valves at €25 {separator} 2 elbows at 10"
    proposal = item_proposal(message, price="25")
    proposal = ProposedNotes.model_validate(
        {
            **proposal.model_dump(),
            "line_items": [
                {"description": "valves", "quantity": "3", "unit_price": "25"},
                {"description": "elbows", "quantity": "2", "unit_price": "10"},
            ],
        }
    )
    updated = apply_proposal(InvoiceNotes(), proposal, message)
    assert [item.model_dump() for item in updated.line_items] == [
        {"description": "valves", "quantity": "3", "unit_price": "25"},
        {"description": "elbows", "quantity": "2", "unit_price": "10"},
    ]


@pytest.mark.parametrize("message", ["3 valves at €25 at 10", "3 valves price €25 cost 10"])
def test_multiple_unbound_price_markers_request_clarification(message):
    for price in ("25", "10"):
        with pytest.raises(ValueError):
            apply_proposal(InvoiceNotes(), item_proposal(message, price=price), message)


def test_quantity_only_patch_cannot_discard_a_conflicting_stated_total():
    message = "Make quantity 5 valves for total €75"
    raw = patch(message).model_dump()
    raw["line_item_patches"][0]["changes"] = [
        {"field": "quantity", "value": "5", "evidence": message}
    ]
    proposal = ProposedNotes.model_validate(raw)
    original = saved_items()
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, proposal, message, expected_version=7, current_version=7)
    assert original.model_dump() == before


@pytest.mark.parametrize("suffix", ["", " total €75"])
def test_total_of_quantity_is_distinct_from_a_monetary_total(suffix):
    message = "a total of 3 valves at €25 each" + suffix
    updated = apply_proposal(InvoiceNotes(), item_proposal(message, price="25"), message)
    assert updated.line_items[0].model_dump() == {
        "description": "valves",
        "quantity": "3",
        "unit_price": "25",
    }


@pytest.mark.parametrize("price", ["25", "30"])
def test_repeated_item_clauses_cannot_select_one_of_conflicting_prices(price):
    message = "3 valves at €25; 3 valves at €30"
    assert not numeric_evidence(
        price, message, message, role="unit_price", item_description="valves"
    )
    with pytest.raises(ValueError):
        apply_proposal(InvoiceNotes(), item_proposal(message, price=price), message)


def test_cropped_patch_cannot_choose_a_repeated_original_item_clause():
    message = "Make valves price €30; make valves price €40"
    cropped = "valves price €30"
    raw = patch(message, value="30", evidence=cropped).model_dump()
    raw["line_item_patches"][0]["evidence"] = cropped
    original = saved_items()
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(
            original,
            ProposedNotes.model_validate(raw),
            message,
            expected_version=7,
            current_version=7,
        )
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message",
    [
        "Make valves quantity 3.000 total €75",
        "Make valves total €75 cost 25.000",
    ],
)
def test_derivation_cannot_drop_invalid_numeric_evidence(message):
    original = saved_items()
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(
            original, patch(message, value="25"), message, expected_version=7, current_version=7
        )
    assert original.model_dump() == before


def test_many_unresolved_item_prices_are_bounded():
    import subprocess
    import sys

    code = """
from anoifig.tara.financial import numeric_evidence
message = '3 valves ' + 'at 3 ' * 500
assert not numeric_evidence('3', message, message, role='unit_price', item_description='valves')
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=3)


def test_a_work_description_mention_does_not_compete_with_the_item_assertion():
    message = "For Gráinne: supply valves, 3 valves at €25 each."
    updated = apply_proposal(InvoiceNotes(), item_proposal(message, price="25"), message)
    assert updated.line_items[0].model_dump() == {
        "description": "valves",
        "quantity": "3",
        "unit_price": "25",
    }
