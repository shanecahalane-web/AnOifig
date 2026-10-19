"""Full-message financial assertions, clause bindings and safe clarification."""

import subprocess
import sys

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
@pytest.mark.parametrize(
    "expression",
    [
        "500 SEK",
        "sek 500",
        "sEk 500",
        "USD 500",
        "usd 500",
        "500 DOLLARS",
        "500 Canadian dollars",
        "500 Swedish crowns",
        "500 New Zealand dollars",
        "500 Swiss francs",
        "negative EUR 500",
        "EUR negative 500",
        "minus euro 500",
        "EUR −500",
        "(500 EUR)",
        "(500 €)",
        "500-",
        "500 EUR −",
        "GBP EUR 500",
        "500 EUR USD",
        "1 500",
        "1\u202f500",
        "1'500",
        "500 .00",
        "500 ,00",
        "500, 00",
        "500.,00",
        "500 1/2",
        "500 k",
        "500 thousand",
        "500 × 2",
        "500 − €20",
        "500 – 20",
        "500 or -700",
        "500 or 700.001",
    ],
)
def test_complete_expression_cannot_be_laundered_by_numeric_evidence(field, expression):
    message = f"Change the {field} to {expression}"
    original = InvoiceNotes(amount="450", labour="100", materials="350")
    before = original.model_dump()
    # Both the complete proposed evidence and a cropped numeric span must reject.
    for evidence in (message, "500"):
        with pytest.raises(ValueError):
            apply_proposal(original, scalar(field, "500", evidence), message)
        assert original.model_dump() == before


@pytest.mark.parametrize(
    "message,value",
    [
        ("Might be €500 or €600; I am not sure", "500"),
        ("Maybe the total is €500", "500"),
        ("Change total to 1e−3", "1"),
        ("Change total to 1 e–3", "1"),
        ("Change amount from €500 to €600", "500"),
        ("Change amount from €500 to €600", "600"),
        ("The amount was €500, now €600", "500"),
        ("Total €500, or alternatively €600", "600"),
        ("Amount due €100 deposit €50", "50"),
        ("Do not change labour and amount €500", "500"),
    ],
)
def test_uncertain_alternative_or_historical_values_preserve_validated_notes(message, value):
    original = InvoiceNotes(amount="450")
    with pytest.raises(ValueError):
        apply_proposal(original, scalar("amount", value, message), message)
    assert original.amount == "450"


@pytest.mark.parametrize(
    "message,value",
    [
        ("Invoice Áine €1,500 for boiler repairs", "1500"),
        ("Invoice John €1,500.25 for repairs", "1500.25"),
        ("Charge 500 EUR", "500"),
        ("Charge EUR500", "500"),
        ("Charge eur 500", "500"),
        ("Charge EuRo 500", "500"),
        ("Charge 500 EUROs", "500"),
        ("Charge 500e", "500"),
        ("Charge 1.5k for the job", "1500"),
        ("Invoice John €500 no VAT", "500"),
        ("Invoice John €500 not VAT registered", "500"),
        ("Invoice John €500 for 3 hours work", "500"),
        ("Invoice John at No. 3 Main Street for €500", "500"),
        ("For the estimate, make the total €500", "500"),
        ("Call 01 555 0123; amount €1,500.25", "1500.25"),
        ("The amount is €500 and VAT rate is 23%", "500"),
    ],
)
def test_supported_irish_invoice_amounts_survive_adjacent_nonfinancial_numbers(message, value):
    result = apply_proposal(InvoiceNotes(), scalar("amount", value, message), message)
    assert result.amount == value


def test_scalar_roles_cannot_exchange_labour_and_materials():
    message = "€100 for labour plus €200 for materials"
    notes = InvoiceNotes(labour="90", materials="180")
    with pytest.raises(ValueError):
        apply_proposal(notes, scalar("labour", "200", message), message)
    result = apply_proposal(notes, scalar("labour", "100", message), message)
    result = apply_proposal(result, scalar("materials", "200", message), message)
    assert (result.labour, result.materials) == ("100", "200")


@pytest.mark.parametrize("field", ["amount", "labour", "materials"])
@pytest.mark.parametrize(
    "expression,value",
    [("3x25", "3"), ("3X€25", "25"), ("500 x 2", "500"), ("3 x EUR25", "25")],
)
def test_quantity_shorthand_cannot_become_a_scalar_charge(field, expression, value):
    message = f"Change {field} to {expression}"
    original = InvoiceNotes(amount="450", labour="100", materials="350")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, scalar(field, value, message), message)
    assert original.model_dump() == before


def stored_items():
    return InvoiceNotes.model_validate(
        {
            "line_items": [
                {"description": "valves", "quantity": "3", "unit_price": "25"},
                {"description": "elbows", "quantity": "2", "unit_price": "10"},
            ]
        }
    )


def patch(evidence, value_evidence, *, index=0, field="unit_price", value="30"):
    descriptions = ["valves", "elbows"]
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [],
            "line_items": None,
            "line_items_evidence": None,
            "line_item_patches": [
                {
                    "index": index,
                    "description": descriptions[index],
                    "evidence": evidence,
                    "changes": [{"field": field, "value": value, "evidence": value_evidence}],
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "message,selector,number,index,field,value",
    [
        ("Make elbows €30 each; valves stay €25", "€30 each; valves", "30", 0, "unit_price", "30"),
        ("Make elbows €30 each, valves stay €25", "€30 each, valves", "30", 0, "unit_price", "30"),
        (
            "Make elbows €30 each and valves stay €25",
            "€30 each and valves",
            "30",
            0,
            "unit_price",
            "30",
        ),
        ("Do not change valves and elbows at €30", "elbows at €30", "30", 1, "unit_price", "30"),
        ("Do not change elbows to €30", "Do not change elbows to €30", "30", 1, "unit_price", "30"),
        ("Make 3 valves total €75", "Make 3 valves total €75", "75", 0, "unit_price", "75"),
        (
            "3 valves delivered within 30 days at €25 each",
            "3 valves delivered within 30 days at €25 each",
            "30",
            0,
            "quantity",
            "30",
        ),
        (
            "Change 3 valves from €25 to €30",
            "Change 3 valves from €25 to €30",
            "25",
            0,
            "unit_price",
            "25",
        ),
        (
            "Change 3 valves to €30 instead of €25",
            "Change 3 valves to €30 instead of €25",
            "25",
            0,
            "unit_price",
            "25",
        ),
    ],
)
def test_item_selector_price_quantity_and_polarity_share_one_original_clause(
    message, selector, number, index, field, value
):
    original = stored_items()
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(
            original,
            patch(selector, number, index=index, field=field, value=value),
            message,
            expected_version=4,
            current_version=4,
        )
    assert original.model_dump() == before


@pytest.mark.parametrize("separator", [";", ",", " and "])
def test_correct_item_update_preserves_explicit_unchanged_item(separator):
    clause = "Make elbows €30 each"
    message = clause + separator + " valves stay €25"
    result = apply_proposal(
        stored_items(), patch(clause, "30", index=1), message, expected_version=4, current_version=4
    )
    assert result.line_items[0].model_dump() == stored_items().line_items[0].model_dump()
    assert result.line_items[1].model_dump() == {
        "description": "elbows",
        "quantity": "2",
        "unit_price": "30",
    }


def replacement(message, *, quantity="3", price="10", description="valves"):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [],
            "line_items": [{"description": description, "quantity": quantity, "unit_price": price}],
            "line_items_evidence": message,
        }
    )


@pytest.mark.parametrize("separator", ["plus", "&", "with", "and", ";"])
def test_initial_item_cannot_borrow_an_unproposed_items_price(separator):
    message = f"3 valves at €25 {separator} 2 elbows at €10"
    with pytest.raises(ValueError):
        apply_proposal(InvoiceNotes(), replacement(message), message)


def test_selective_correction_cannot_drop_other_existing_items_via_replacement():
    message = "Make 2 elbows €30 each; valves stay €25"
    original = stored_items()
    with pytest.raises(ValueError):
        apply_proposal(
            original,
            replacement(message, quantity="2", price="30", description="elbows"),
            message,
            expected_version=4,
            current_version=4,
        )
    assert len(original.line_items) == 2


def test_whole_list_replacement_requires_explicit_user_instruction():
    message = "Replace all line items with 4 couplings at €5 each"
    result = apply_proposal(
        stored_items(),
        replacement(message, quantity="4", price="5", description="couplings"),
        message,
    )
    assert len(result.line_items) == 1
    assert result.line_items[0].description == "couplings"


@pytest.mark.parametrize(
    "message",
    [
        "Do not use VAT rate 23%",
        "Not VAT rate 23%",
        "VAT 23% or 13.5%",
        "Do not change VAT and VAT 23%",
        "Maybe VAT 23%",
        "If VAT rate is 23%",
        "VAT 23% or -13.5%",
        "Never use 23% VAT",
        "VAT rate 23% is not correct",
    ],
)
def test_vat_rate_assertion_requires_positive_unambiguous_full_message(message):
    original = InvoiceNotes(vat_rate="13.5", vat_basis="exclusive")
    for evidence in (message, "23"):
        with pytest.raises(ValueError):
            apply_proposal(original, scalar("vat_rate", "23", evidence), message)
    assert original.vat_rate == "13.5"


@pytest.mark.parametrize(
    "message",
    [
        "Maybe VAT included",
        "If VAT included",
        "Do not use VAT included",
        "VAT included or before VAT",
        "Do not change VAT and VAT included",
    ],
)
def test_vat_basis_cannot_crop_away_uncertainty_or_shared_negation(message):
    original = InvoiceNotes(vat_basis="exclusive")
    with pytest.raises(ValueError):
        apply_proposal(original, scalar("vat_basis", "inclusive", "VAT included"), message)
    assert original.vat_basis == "exclusive"


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Use VAT rate 13.5%, excluding VAT", "vat_rate", "13.5"),
        ("The VAT rate is 23", "vat_rate", "23"),
        ("Including VAT", "vat_basis", "inclusive"),
        ("Not registered for VAT", "vat_basis", "no_vat"),
    ],
)
def test_affirmative_explicit_vat_still_passes(message, field, value):
    result = apply_proposal(InvoiceNotes(), scalar(field, value, message), message)
    assert getattr(result, field) == value


def test_repeated_currency_tokens_cannot_pin_the_worker_in_regex_backtracking():
    # A separate interpreter bounds a regression without leaving a stuck test
    # thread behind. Previous non-atomic currency alternatives exceed this limit
    # with only 30 repetitions; the message here remains below ingress limits.
    code = """
from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal
message = 'EUR ' * 800 + 'reference abc500; Charge 500 SEK'
notes = InvoiceNotes(amount='450')
proposal = ProposedNotes.model_validate({
    'intent':'correction', 'changes':[{'field':'amount','value':'500','evidence':message}],
    'line_items':None, 'line_items_evidence':None,
})
try:
    apply_proposal(notes, proposal, message)
except ValueError:
    assert notes.amount == '450'
else:
    raise AssertionError('Unsupported financial expression accepted')
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, timeout=3)
