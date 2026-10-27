"""Adjacent authority probes found while auditing the six scoped corrections."""

import pytest

from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal

ITEMS = [
    {"description": "valves", "quantity": "3", "unit_price": "25"},
    {"description": "elbows", "quantity": "2", "unit_price": "10"},
]


def proposal(field, value, evidence, *, item=False):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [] if item else [{"field": field, "value": value, "evidence": evidence}],
            "line_items": None,
            "line_items_evidence": None,
            "line_item_patches": [
                {
                    "index": 0,
                    "description": "valves",
                    "evidence": evidence,
                    "changes": [{"field": field, "value": value, "evidence": evidence}],
                }
            ]
            if item
            else [],
        }
    )


@pytest.mark.parametrize(
    "message,field,value,accepted",
    [
        ('The old invoice says "now use VAT 0%".', "vat_rate", "0", False),
        ('The old invoice says "this one is VAT 0%".', "vat_rate", "0", False),
        ('The old invoice says "instead use VAT 0%".', "vat_rate", "0", False),
        ("The old invoice instruction was: now use VAT 0%.", "vat_rate", "0", False),
        ("Which rate applies?\n- VAT 23%", "vat_rate", "23", False),
        ("Which treatment applies?\n1) including VAT", "vat_basis", "inclusive", False),
        (
            "Set work description repair customer boiler.",
            "work_description",
            "repair customer boiler",
            True,
        ),
        ("Set work description paint name signs.", "work_description", "paint name signs", True),
        ("Work description: replace name plate.", "work_description", "replace name plate", True),
        (
            "Set customer name Customer Care Heating.",
            "customer_name",
            "Customer Care Heating",
            True,
        ),
        ("Set customer details 25 Customer Road.", "customer_details", "25 Customer Road", True),
        ("Invoice John for repairs; invoice Mary for repairs.", "customer_name", "John", False),
        ("For John; for Mary.", "customer_name", "John", False),
        (
            "Invoice John €500 for repairs; this invoice is for Mary.",
            "customer_name",
            "John",
            False,
        ),
    ],
)
def test_reported_speech_role_owned_payloads_and_implicit_field_conflicts(
    message, field, value, accepted
):
    notes = InvoiceNotes(
        customer_name="John",
        work_description="repairs",
        customer_details="1 Oak Road",
        amount="600",
        labour="400",
        materials="200",
        vat_basis="exclusive",
        vat_rate="13.5",
    )
    before = notes.model_dump()
    change = proposal(field, value, value)
    if accepted:
        assert apply_proposal(notes, change, message).model_dump() == {**before, field: value}
    else:
        with pytest.raises(ValueError):
            apply_proposal(notes, change, message)
    assert notes.model_dump() == before


@pytest.mark.parametrize(
    "continuation,accepted",
    [
        ("keep elbows unchanged.", True),
        ("keep elbows in this invoice unchanged.", True),
        ("keep VAT on this invoice unchanged.", True),
        ("leave the elbows on the invoice as is.", True),
        ("no changes please.", False),
        ("scratch that.", False),
        ("scrap that.", False),
        ("never mind.", False),
        ("do not ever apply that change.", False),
        ("don't you make this change.", False),
    ],
)
def test_preservation_context_does_not_expand_a_named_target_to_the_entire_document(
    continuation, accepted
):
    evidence = "Change valves unit price €30 each"
    notes = InvoiceNotes(vat_basis="no_vat", line_items=ITEMS)
    before = notes.model_dump()
    change = proposal("unit_price", "30", evidence, item=True)
    message = evidence + "; " + continuation
    if accepted:
        assert apply_proposal(
            notes, change, message, expected_version=1, current_version=1
        ).model_dump() == {
            **before,
            "line_items": [{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
        }
    else:
        with pytest.raises(ValueError):
            apply_proposal(notes, change, message, expected_version=1, current_version=1)
    assert notes.model_dump() == before


@pytest.mark.parametrize(
    "continuation",
    [
        "keep the description unchanged.",
        "keep the line description unchanged.",
        "do not change the description.",
        "keep the item description unchanged.",
    ],
)
def test_item_description_preservation_is_not_mistaken_for_only_work_description(continuation):
    evidence = "Rename valves to valve assemblies"
    notes = InvoiceNotes(vat_basis="no_vat", line_items=ITEMS)
    before = notes.model_dump()
    change = proposal("description", "valve assemblies", evidence, item=True)
    with pytest.raises(ValueError):
        apply_proposal(
            notes,
            change,
            evidence + "; " + continuation,
            expected_version=1,
            current_version=1,
        )
    assert notes.model_dump() == before


@pytest.mark.parametrize("cropped", [False, True])
def test_customer_question_heading_cannot_confirm_a_suggested_name(cropped):
    message = "*Who should we invoice?*\n- Jack"
    notes = InvoiceNotes(amount="600", labour="400", materials="200")
    before = notes.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(
            notes, proposal("customer_name", "Jack", "Jack" if cropped else message), message
        )
    assert notes.model_dump() == before


def test_independent_explicit_customer_instruction_can_follow_a_social_question():
    message = "How are you?\nSet customer name Jack"
    notes = InvoiceNotes(customer_name="John", amount="600")
    assert apply_proposal(
        notes, proposal("customer_name", "Jack", "Jack"), message
    ).model_dump() == {
        **notes.model_dump(),
        "customer_name": "Jack",
    }
