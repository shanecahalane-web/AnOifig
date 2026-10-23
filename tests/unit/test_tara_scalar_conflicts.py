"""The final boundary retains contradictory explicit scalar assertions."""

import pytest

from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal


def scalar(field, value, evidence):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [{"field": field, "value": value, "evidence": evidence}],
            "line_items": None,
            "line_items_evidence": None,
        }
    )


@pytest.mark.parametrize("field", ["amount", "labour", "materials"])
def test_conflicting_current_scalar_assertions_cannot_be_cropped(field):
    evidence = f"Set {field} €500"
    message = evidence + f"; {field} €600"
    original = InvoiceNotes(amount="450", labour="100", materials="350")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, scalar(field, "500", evidence), message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message",
    ["Set labour €500; materials €600", "Set labour €500; the old invoice labour €600"],
)
def test_other_roles_and_historical_scalar_assertions_are_independent(message):
    original = InvoiceNotes(labour="450")
    updated = apply_proposal(original, scalar("labour", "500", "Set labour €500"), message)
    assert updated.model_dump() == {**original.model_dump(), "labour": "500"}


def test_line_totals_are_not_competing_scalar_invoice_amounts():
    message = "3 valves line total €75 and 2 elbows line total €20; invoice total €95"
    original = InvoiceNotes(vat_basis="no_vat")
    items = [
        {"description": "valves", "quantity": "3", "unit_price": "25"},
        {"description": "elbows", "quantity": "2", "unit_price": "10"},
    ]
    proposal = ProposedNotes.model_validate(
        {
            "intent": "invoice_preparation",
            "changes": [],
            "line_items": items,
            "line_items_evidence": message,
        }
    )
    assert apply_proposal(original, proposal, message).model_dump() == {
        **original.model_dump(),
        "line_items": items,
    }


@pytest.mark.parametrize("label", ["total", "for this invoice, total"])
@pytest.mark.parametrize("total,accepted", [("90", False), ("110", True)])
def test_a_total_without_an_item_target_is_checked_against_the_complete_result(
    label, total, accepted
):
    original = InvoiceNotes(
        vat_basis="no_vat",
        line_items=[
            {"description": "valves", "quantity": "3", "unit_price": "25"},
            {"description": "elbows", "quantity": "2", "unit_price": "10"},
        ],
    )
    evidence = "Make valves unit price €30 each"
    message = evidence + f"; {label} €{total}"
    proposal = ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [],
            "line_items": None,
            "line_items_evidence": None,
            "line_item_patches": [
                {
                    "index": 0,
                    "description": "valves",
                    "evidence": evidence,
                    "changes": [{"field": "unit_price", "value": "30", "evidence": evidence}],
                }
            ],
        }
    )
    if not accepted:
        with pytest.raises(ValueError):
            apply_proposal(original, proposal, message, expected_version=1, current_version=1)
    else:
        assert (
            apply_proposal(original, proposal, message, expected_version=1, current_version=1)
            .line_items[0]
            .unit_price
            == "30"
        )
