"""Aggregate amounts and formatted/current VAT assertions retain their scope."""

from decimal import Decimal

import pytest

from anoifig.tara.financial import invoice_total_matches, item_clauses, unit_price_evidence
from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal

ITEMS = [
    {"description": "valves", "quantity": "3", "unit_price": "25"},
    {"description": "elbows", "quantity": "2", "unit_price": "10"},
]
AGGREGATE_LABELS = [
    "total for all the items",
    "total for all of the items",
    "total for both of the items",
    "total for all line items",
]
VAT_LISTS = [
    ("Which VAT treatment applies?\n- VAT 23%", "vat_rate", "23", "23%"),
    ("Which VAT treatment applies?\n1. VAT 23%", "vat_rate", "23", "23%"),
    ("Which VAT treatment applies?\n(a) VAT 23%", "vat_rate", "23", "23%"),
    ("Which VAT treatment applies?\n\n  - VAT 23%", "vat_rate", "23", "23%"),
    ("Which VAT treatment applies?; - VAT 23%", "vat_rate", "23", "23%"),
    ("Which VAT treatment applies?:\n  * VAT 23%.", "vat_rate", "23", "23%"),
    ("Which VAT treatment applies?\n- including VAT", "vat_basis", "inclusive", "including VAT"),
    ("Which VAT treatment applies?\n2) including VAT", "vat_basis", "inclusive", "including VAT"),
    ("Which VAT treatment applies?\nb. including VAT", "vat_basis", "inclusive", "including VAT"),
    (
        "Which VAT treatment applies?\n\n    - including VAT",
        "vat_basis",
        "inclusive",
        "including VAT",
    ),
    ("Which VAT treatment applies?; - including VAT", "vat_basis", "inclusive", "including VAT"),
    (
        "Which VAT treatment applies?:\n  * including VAT.",
        "vat_basis",
        "inclusive",
        "including VAT",
    ),
]
HISTORICAL_CURRENT = [
    ("the old invoice", "this invoice"),
    ("the previous invoice", "the current invoice"),
    ("the last job", "the new invoice"),
    ("the earlier bill", "the invoice being prepared"),
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


def saved(*, items=True, vat_basis="no_vat"):
    return InvoiceNotes(
        customer_name="John",
        work_description="repairs",
        customer_details="1 Oak Road",
        vat_basis=vat_basis,
        vat_rate="13.5" if vat_basis != "no_vat" else None,
        line_items=ITEMS if items else [],
    )


def patch(message, value="30", *, field="unit_price", evidence=None):
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


@pytest.mark.parametrize("label", AGGREGATE_LABELS)
@pytest.mark.parametrize("price", ["30", "90"], ids=["exact-product", "literal-amount"])
def test_aggregate_labels_cannot_supply_a_selected_lines_price(label, price):
    message = f"Change valves so the {label} is €90"
    context = item_clauses(message, "valves")[0].text
    assert not unit_price_evidence(
        price,
        message,
        message,
        quantity="3",
        within=context,
        item_description="valves",
        allow_existing_quantity=True,
    )


@pytest.mark.parametrize("label", AGGREGATE_LABELS)
@pytest.mark.parametrize("path", ["initial", "replacement", "price-patch", "quantity-patch"])
def test_aggregate_scope_is_enforced_on_every_item_write_path(label, path):
    original = saved(items=path != "initial")
    if path in {"initial", "replacement"}:
        prefix = "Replace all line items with: " if path == "replacement" else ""
        message = f"{prefix}3 valves for a {label} of €90 and 2 elbows at €10"
        p = proposed(
            line_items=[{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
            line_items_evidence=message,
        )
    elif path == "quantity-patch":
        message = f"Change valves quantity to 4 so the {label} is €100"
        p = patch(message, "4", field="quantity")
    else:
        # Keep the reported message byte-for-byte, including its missing full stop.
        message = f"Change valves so the {label} is €90"
        p = patch(message)
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, p, message, expected_version=4, current_version=4)
    assert original.model_dump() == before


def test_cropped_evidence_cannot_allocate_an_aggregate_amount():
    message = "Change valves so the total for all the items is €90"
    original = saved()
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(
            original,
            patch(message, evidence="€90"),
            message,
            expected_version=4,
            current_version=4,
        )
    assert original.model_dump() == before


@pytest.mark.parametrize("label", AGGREGATE_LABELS)
@pytest.mark.parametrize("total,accepted", [("90", False), ("110", True)])
def test_explicit_units_and_aggregate_amount_use_every_resulting_item(label, total, accepted):
    message = f"Make valves unit price €30 each; {label} €{total}"
    original = saved()
    p = patch("Make valves unit price €30 each")
    before = original.model_dump()
    if accepted:
        updated = apply_proposal(original, p, message, expected_version=4, current_version=4)
        assert updated.model_dump() == {
            **before,
            "line_items": [{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
        }
    else:
        with pytest.raises(ValueError):
            apply_proposal(original, p, message, expected_version=4, current_version=4)
    assert original.model_dump() == before
    assert (
        invoice_total_matches(
            message,
            Decimal("110"),
            item_descriptions=("valves", "elbows"),
        )
        is accepted
    )


@pytest.mark.parametrize("message,field,value,evidence", VAT_LISTS)
@pytest.mark.parametrize("cropped", [False, True])
def test_question_heading_remains_attached_to_formatted_vat_assertions(
    message, field, value, evidence, cropped
):
    original = saved(vat_basis="exclusive")
    before = original.model_dump()
    p = proposed(
        changes=[{"field": field, "value": value, "evidence": evidence if cropped else message}]
    )
    with pytest.raises(ValueError):
        apply_proposal(original, p, message)
    assert original.model_dump() == before


@pytest.mark.parametrize("historical,current", HISTORICAL_CURRENT)
@pytest.mark.parametrize("field", ["vat_rate", "vat_basis"])
@pytest.mark.parametrize("cropped", [False, True])
def test_historical_tax_scope_ends_before_a_current_invoice_assertion(
    historical, current, field, cropped
):
    if field == "vat_rate":
        message = f"Use VAT 23%; {historical} is exempt, but {current} is VAT 0%"
        value, evidence = "23", "23%"
    else:
        message = f"Use including VAT; {historical} is exempt, but {current} is excluding VAT"
        value, evidence = "inclusive", "including VAT"
    original = saved(vat_basis="exclusive")
    before = original.model_dump()
    p = proposed(
        changes=[{"field": field, "value": value, "evidence": evidence if cropped else message}]
    )
    with pytest.raises(ValueError):
        apply_proposal(original, p, message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message",
    [
        "Make valves unit price €30 each",
        "Make valves line total €90",
        "Make valves overall price €90",
        "Make valves price per unit €30; total for all the items €110",
    ],
)
def test_explicit_unit_and_item_bound_totals_keep_their_supported_meaning(message):
    original = saved()
    evidence = message.split(";")[0]
    updated = apply_proposal(
        original, patch(evidence), message, expected_version=4, current_version=4
    )
    assert updated.model_dump() == {
        **original.model_dump(),
        "line_items": [{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
    }


@pytest.mark.parametrize(
    "message,changes",
    [
        ("Use VAT 23%; including VAT", [("vat_rate", "23"), ("vat_basis", "inclusive")]),
        ("Use VAT 23%. The old invoice was exempt.", [("vat_rate", "23")]),
        ("Use VAT 23%; the previous invoice was exempt.", [("vat_rate", "23")]),
        ("Use VAT 23%; the last job was exempt.", [("vat_rate", "23")]),
        ("Use including VAT; the earlier bill was exempt.", [("vat_basis", "inclusive")]),
        (
            "Use VAT 23%; which repairs apply?\nincluding VAT",
            [("vat_rate", "23"), ("vat_basis", "inclusive")],
        ),
    ],
)
def test_independent_affirmative_vat_facts_and_historical_facts_remain_supported(message, changes):
    original = saved(vat_basis="exclusive")
    p = proposed(
        changes=[{"field": field, "value": value, "evidence": message} for field, value in changes]
    )
    assert apply_proposal(original, p, message).model_dump() == {
        **original.model_dump(),
        **dict(changes),
    }
