"""Adversarial financial evidence and version-bound selective correction invariants."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from anoifig.tara.schemas import (
    InvoiceNotes,
    ProposedNotes,
    apply_proposal,
    money,
    numeric_evidence,
)


def proposal(field, value, evidence):
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
    ("message", "value", "evidence"),
    [
        ("Invoice John €1500", "500", "500"),
        ("Change it to -500", "500", "500"),
        ("Change it to - €500", "500", "500"),
        ("Change it to −500", "500", "500"),
        ("Change it to £500", "500", "500"),
        ("Change it to $500", "500", "500"),
        ("Change it to 500 GBP", "500", "500"),
        ("Change it to USD 500", "500", "500"),
        ("Change it to 500 dollars", "500", "500"),
        ("Change it to 500 CAD", "500", "500"),
        ("Change it to 1e3", "3", "3"),
        ("Change it to 1e3", "1", "1"),
        ("Change it to 1e+3", "3", "3"),
        ("Change it to 1 e 3", "3", "3"),
        ("Change it to 500.001", "500", "500"),
        ("Change it to €1,500", "500", "500"),
        ("Change it to 1.5k", "1.5", "1.5"),
        ("Change it to 23% VAT", "23", "23"),
        ("Change it to 23 percent VAT", "23", "23"),
        ("Change it to 500USD", "500", "500"),
        ("Change it to abc500", "500", "500"),
        ("Change it to 0x500", "500", "500"),
        ("Change it to €500.00", "500", "500"),
        ("Change it to 500+20", "500", "500"),
        ("Change it to 500 / 2", "500", "500"),
        ("Change it to €500 - €20", "500", "500"),
        ("Change it to 500*2", "500", "500"),
        ("It was £500, now €500", "500", "500"),
        ("It was €1500, now €500", "500", "500"),
        ("Change it to £€500", "500", "500"),
        ("Change it to USD €500", "500", "500"),
        ("Change it to 500.000", "500", "500.000"),
        ("Change it to 0.500", "0.5", "0.500"),
        ("Change it to 500..00", "500", "500"),
        ("Change it to (500)", "500", "500"),
        ("Change it to 1.234k", "1234", "1.234k"),
        ("Change it to € 500 USD", "500", "500"),
        ("Change it to minus €500", "500", "500"),
        ("Change it to negative 500", "500", "500"),
        ("Change it to NEGATIVE € 500.00", "500", "500.00"),
    ],
)
def test_model_cannot_crop_a_financial_token_to_change_its_meaning(field, message, value, evidence):
    original = InvoiceNotes(amount="450", labour="100", materials="350")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, proposal(field, value, evidence), message)
    assert original.model_dump() == before


def test_every_cropped_numeric_subspan_of_large_or_precise_amounts_is_rejected():
    # Enumerate adversarial evidence choices rather than preselecting a harmless
    # complete evidence span. None can turn a substring into a different amount.
    for token in ("1500", "97531", "500.001", "0.500", "1,500.25"):
        source = "The charge is €" + token
        for start in range(len(token)):
            for end in range(start + 1, len(token) + 1):
                cropped = token[start:end]
                try:
                    candidate = money(cropped)
                except ValueError:
                    continue
                if candidate == Decimal(token.replace(",", "")):
                    continue
                with pytest.raises(ValueError):
                    apply_proposal(InvoiceNotes(), proposal("amount", cropped, cropped), source)


@pytest.mark.parametrize(
    ("message", "value", "evidence"),
    [
        ("Make it €500", "500", "500"),
        ("Make it €500.00", "500", "500.00"),
        ("Make it 500e, cheers", "500", "500e"),
        ("Make it 1.5k for the job", "1500", "1.5k"),
        ("Make it €1,500.25", "1500.25", "€1,500.25"),
        ("Make it 450EUR", "450", "450EUR"),
    ],
)
def test_complete_supported_money_is_preserved_without_float_arithmetic(message, value, evidence):
    updated = apply_proposal(InvoiceNotes(), proposal("amount", value, evidence), message)
    assert updated.amount == value
    assert money(updated.amount) == Decimal(value)


@pytest.mark.parametrize(
    ("field", "value", "message", "evidence"),
    [
        ("vat_rate", "23", "The job price is €23", "23"),
        ("vat_rate", "23", "VAT unknown; the job costs €23", "23"),
        ("vat_rate", "23", "VAT is €23", "23"),
        ("vat_rate", "23", "VAT rate is 13.5%, price €23", "23"),
        ("vat_basis", "exclusive", "Finish it before Friday", "before"),
        ("vat_basis", "inclusive", "Including all labour", "Including"),
        ("vat_basis", "inclusive", "Not including VAT", "including VAT"),
        ("vat_basis", "no_vat", "No VAT rate information available", "No VAT"),
        ("vat_basis", "inclusive", "VAT included in €500", "500"),
        ("vat_basis", "inclusive", "Including VAT or excluding VAT", "Including VAT"),
        ("vat_basis", "no_vat", "Not VAT registered, including VAT", "Not VAT registered"),
        ("vat_rate", "23", "VAT 23% or VAT 13.5%", "23"),
        ("vat_rate", "23", "VAT rate is 23 EUR", "23"),
        ("vat_rate", "23", "€23% VAT", "23"),
        ("vat_rate", "23", "Not 23% VAT", "23"),
        ("vat_basis", "inclusive", "Not VAT included", "VAT included"),
        ("vat_basis", "inclusive", "Not actually including VAT", "including VAT"),
        ("vat_basis", "no_vat", "Not VAT exempt", "VAT exempt"),
    ],
)
def test_vat_requires_explicit_relevant_evidence(field, value, message, evidence):
    with pytest.raises(ValueError):
        apply_proposal(InvoiceNotes(), proposal(field, value, evidence), message)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("vat_rate", "23", "VAT 23 percent"),
        ("vat_rate", "13.5", "13.5% VAT"),
        ("vat_rate", "23", "The VAT rate is 23"),
        ("vat_basis", "inclusive", "Including VAT"),
        ("vat_basis", "exclusive", "Before VAT"),
        ("vat_basis", "exclusive", "Plus VAT"),
        ("vat_basis", "no_vat", "Not registered for VAT"),
    ],
)
def test_explicit_vat_statements_need_no_pending_question(field, value, message):
    updated = apply_proposal(InvoiceNotes(), proposal(field, value, message), message)
    assert getattr(updated, field) == value


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("vat_rate", "23", "23"),
        ("vat_rate", "13.5", "13.5%"),
        ("vat_rate", "23", "23 percent."),
        ("vat_basis", "exclusive", "Before"),
        ("vat_basis", "inclusive", "Including"),
        ("vat_basis", "no_vat", "Not registered"),
    ],
)
def test_short_vat_answers_require_the_exact_application_bound_pending_question(
    field, value, message
):
    change = proposal(field, value, message)
    with pytest.raises(ValueError):
        apply_proposal(InvoiceNotes(), change, message)
    with pytest.raises(ValueError):
        apply_proposal(
            InvoiceNotes(),
            change,
            message,
            pending_clarification="vat_basis" if field == "vat_rate" else "vat_rate",
        )
    updated = apply_proposal(InvoiceNotes(), change, message, pending_clarification=field)
    assert getattr(updated, field) == value


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("vat_rate", "23", "€23"),
        ("vat_rate", "23", "23 euro"),
        ("vat_rate", "23", "23 for the job"),
        ("vat_basis", "exclusive", "Before Friday"),
        ("vat_basis", "inclusive", "Including labour"),
    ],
)
def test_a_pending_vat_question_does_not_make_unrelated_answers_valid(field, value, message):
    with pytest.raises(ValueError):
        apply_proposal(
            InvoiceNotes(), proposal(field, value, message), message, pending_clarification=field
        )


def existing_items():
    return InvoiceNotes.model_validate(
        {
            "customer_name": "John",
            "customer_details": "Synthetic contact reference",
            "line_items": [
                {"description": "valves", "quantity": "3", "unit_price": "25"},
                {"description": "elbows", "quantity": "2", "unit_price": "10"},
            ],
        }
    )


def patch_proposal(message, *, index=0, description="valves", field="unit_price", value="30"):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [],
            "line_items": None,
            "line_items_evidence": None,
            "line_item_patches": [
                {
                    "index": index,
                    "description": description,
                    "evidence": message,
                    "changes": [{"field": field, "value": value, "evidence": message}],
                }
            ],
        }
    )


def test_selective_price_correction_preserves_quantity_other_items_and_other_notes():
    original = existing_items()
    before = original.model_dump()
    message = "Actually make the valves €30 each"
    updated = apply_proposal(
        original, patch_proposal(message), message, expected_version=7, current_version=7
    )
    assert updated.line_items[0].unit_price == "30"
    expected = before.copy()
    expected["line_items"] = [
        {"description": "valves", "quantity": "3", "unit_price": "30"},
        {"description": "elbows", "quantity": "2", "unit_price": "10"},
    ]
    assert updated.model_dump() == expected
    assert original.model_dump() == before


def test_multiple_turns_of_selective_corrections_preserve_three_items():
    message = "Invoice John for 3 valves at €25, 2 elbows at €10 and 4 couplings at €5"
    supplied = [
        {"description": "valves", "quantity": "3", "unit_price": "25"},
        {"description": "elbows", "quantity": "2", "unit_price": "10"},
        {"description": "couplings", "quantity": "4", "unit_price": "5"},
    ]
    initial = ProposedNotes.model_validate(
        {
            "intent": "invoice_preparation",
            "changes": [{"field": "customer_name", "value": "John", "evidence": message}],
            "line_items": supplied,
            "line_items_evidence": message,
        }
    )
    notes = apply_proposal(InvoiceNotes(), initial, message, expected_version=0, current_version=0)
    turns = [
        ("Actually make the valves €30 each", {"value": "30"}),
        (
            "Actually make the elbows quantity 5",
            {"index": 1, "description": "elbows", "field": "quantity", "value": "5"},
        ),
        (
            "Rename couplings to brass couplings",
            {
                "index": 2,
                "description": "couplings",
                "field": "description",
                "value": "brass couplings",
            },
        ),
    ]
    for version, (message, options) in enumerate(turns, start=1):
        notes = apply_proposal(
            notes,
            patch_proposal(message, **options),
            message,
            expected_version=version,
            current_version=version,
        )
    assert notes.customer_name == "John"
    assert [item.model_dump() for item in notes.line_items] == [
        {"description": "valves", "quantity": "3", "unit_price": "30"},
        {"description": "elbows", "quantity": "5", "unit_price": "10"},
        {"description": "brass couplings", "quantity": "4", "unit_price": "5"},
    ]


def test_selective_quantity_and_description_corrections_preserve_other_fields():
    original = existing_items()
    quantity_message = "Actually make the valves quantity 4"
    quantity = apply_proposal(
        original,
        patch_proposal(quantity_message, field="quantity", value="4"),
        quantity_message,
        expected_version=7,
        current_version=7,
    )
    assert quantity.line_items[0].quantity == "4"
    assert quantity.line_items[0].unit_price == "25"
    description_message = "Rename valves to brass valves"
    renamed = apply_proposal(
        original,
        patch_proposal(description_message, field="description", value="brass valves"),
        description_message,
        expected_version=7,
        current_version=7,
    )
    assert renamed.line_items[0].description == "brass valves"
    assert renamed.line_items[0].quantity == "3"
    assert renamed.line_items[0].unit_price == "25"
    assert renamed.line_items[1] == original.line_items[1]


@pytest.mark.parametrize(
    "versions",
    [
        {},
        {"expected_version": 7},
        {"current_version": 7},
        {"expected_version": 6, "current_version": 7},
    ],
)
def test_line_item_patches_fail_without_the_same_application_bound_version(versions):
    original = existing_items()
    before = original.model_dump()
    message = "Actually make the valves €30 each"
    with pytest.raises(ValueError):
        apply_proposal(original, patch_proposal(message), message, **versions)
    assert original.model_dump() == before


def test_stale_version_also_rejects_top_level_changes():
    with pytest.raises(ValueError):
        apply_proposal(
            existing_items(),
            proposal("amount", "500", "500"),
            "Make it €500",
            expected_version=6,
            current_version=7,
        )


@pytest.mark.parametrize(
    "options",
    [
        {"index": 1},
        {"index": 19},
        {"description": "valve"},
        {"description": "another item"},
    ],
)
def test_item_selector_cannot_use_a_wrong_index_or_ambiguous_name(options):
    message = "Actually make the valves €30 each"
    with pytest.raises(ValueError):
        apply_proposal(
            existing_items(),
            patch_proposal(message, **options),
            message,
            expected_version=7,
            current_version=7,
        )


def test_duplicate_existing_descriptions_require_clarification():
    notes = existing_items()
    notes.line_items[1].description = "valves"
    message = "Actually make the valves €30 each"
    with pytest.raises(ValueError):
        apply_proposal(
            notes, patch_proposal(message), message, expected_version=7, current_version=7
        )


@pytest.mark.parametrize("message", ["Make it €30 each", "Make valves and elbows €30 each"])
def test_a_missing_or_multiple_item_mention_is_not_an_item_selector(message):
    with pytest.raises(ValueError):
        apply_proposal(
            existing_items(),
            patch_proposal(message),
            message,
            expected_version=7,
            current_version=7,
        )


@pytest.mark.parametrize("token", ["€130", "-30", "£30", "3e30", "30.001"])
def test_patch_amounts_cannot_bypass_original_token_checks(token):
    message = f"Actually make valves {token} each"
    change = patch_proposal(message)
    change.line_item_patches[0].changes[0].evidence = "30"
    with pytest.raises(ValueError):
        apply_proposal(existing_items(), change, message, expected_version=7, current_version=7)


def test_patch_evidence_cannot_borrow_a_valid_number_from_another_item():
    message = "Make valves £30 each; make elbows €30 each"
    change = patch_proposal("Make valves £30 each")
    change.line_item_patches[0].changes[0].evidence = "30"
    with pytest.raises(ValueError):
        apply_proposal(existing_items(), change, message, expected_version=7, current_version=7)


def test_repeated_patches_and_fields_fail_atomically():
    message = "Actually make valves €30 each"
    for duplicate_item in (True, False):
        change = patch_proposal(message)
        if duplicate_item:
            change.line_item_patches *= 2
        else:
            change.line_item_patches[0].changes *= 2
        notes = existing_items()
        before = notes.model_dump()
        with pytest.raises(ValueError):
            apply_proposal(notes, change, message, expected_version=7, current_version=7)
        assert notes.model_dump() == before


def test_a_patch_cannot_hide_unannounced_changes_in_unchanged_fields():
    message = "Actually make valves €30 each"
    with pytest.raises(ValidationError):
        patch_proposal(message).model_copy().model_validate(
            {
                **patch_proposal(message).model_dump(),
                "line_item_patches": [
                    {
                        **patch_proposal(message).line_item_patches[0].model_dump(),
                        "quantity": "99",
                    }
                ],
            }
        )


def test_replacement_and_patch_cannot_be_combined():
    message = "Actually make valves €30 each"
    change = patch_proposal(message)
    change.line_items = existing_items().line_items
    with pytest.raises(ValueError):
        apply_proposal(existing_items(), change, message, expected_version=7, current_version=7)


def test_replacement_lines_also_validate_against_original_message_tokens():
    source = "3 valves at £25 each"
    replacement = ProposedNotes.model_validate(
        {
            "intent": "invoice_preparation",
            "changes": [],
            "line_items": [{"description": "valves", "quantity": "3", "unit_price": "25"}],
            "line_items_evidence": "3 valves at £25 each",
        }
    )
    with pytest.raises(ValueError):
        apply_proposal(InvoiceNotes(), replacement, source)


def test_numeric_helper_supports_existing_public_two_argument_calls():
    assert numeric_evidence("3", "3x25 for valves")
    assert numeric_evidence("25", "3x25 for valves")
    assert not numeric_evidence("500", "-500")
