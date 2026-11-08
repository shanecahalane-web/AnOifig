"""Whole-message authority regressions for the six independent P2 findings."""

import pytest

from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal

ITEMS = [
    {"description": "valves", "quantity": "3", "unit_price": "25"},
    {"description": "elbows", "quantity": "2", "unit_price": "10"},
]


def saved(*, items=False, vat=False):
    return InvoiceNotes(
        customer_name="John",
        work_description="repairs",
        customer_details="1 Oak Road",
        amount=None if items else "600",
        labour=None if items else "400",
        materials=None if items else "200",
        vat_basis="exclusive" if vat else "no_vat",
        vat_rate="13.5" if vat else None,
        line_items=ITEMS if items else [],
    )


def proposed(*changes, patches=None, **extra):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [
                {"field": field, "value": value, "evidence": evidence}
                for field, value, evidence in changes
            ],
            "line_items": None,
            "line_items_evidence": None,
            "line_item_patches": patches or [],
            **extra,
        }
    )


def item_patch(evidence, value="30", *, field="unit_price", index=0, description="valves"):
    return {
        "index": index,
        "description": description,
        "evidence": evidence,
        "changes": [{"field": field, "value": value, "evidence": evidence}],
    }


def reject(notes, proposal, message):
    before = notes.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(notes, proposal, message, expected_version=7, current_version=7)
    assert notes.model_dump() == before


@pytest.mark.parametrize("field", ["amount", "labour", "materials"])
@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize(
    "message,value",
    [
        ("The address is 25 Main Street.", "25"),
        ("Invoice reference 500.", "500"),
        ("There are 3 valves.", "3"),
        ("The job took 8 hours.", "8"),
    ],
)
def test_nonfinancial_unique_numbers_never_authorise_scalar_changes(field, cropped, message, value):
    reject(saved(), proposed((field, value, value if cropped else message)), message)


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Labour took 8 hours.", "labour", "8"),
        ("Set materials quantity to 3.", "materials", "3"),
        ("Invoice reference €500.", "amount", "500"),
        ("Total quantity 3.", "amount", "3"),
    ],
)
def test_financial_words_do_not_relabel_nonfinancial_numeric_roles(message, field, value):
    reject(saved(), proposed((field, value, value)), message)


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Invoice John €500 for repairs", "labour", "500"),
        ("Invoice John €500 for repairs", "materials", "500"),
        ("€100 for labour", "amount", "100"),
        ("€100 for labour", "materials", "100"),
        ("Materials €200", "amount", "200"),
        ("Materials €200", "labour", "200"),
    ],
)
def test_scalar_amount_must_have_authority_for_its_specific_field(message, field, value):
    reject(saved(), proposed((field, value, message)), message)


@pytest.mark.parametrize(
    "label",
    [
        "total for everything",
        "combined total",
        "total across the two items",
        "total for the lot",
        "total for these items",
        "total of the complete order",
        "joint total",
    ],
)
def test_collective_totals_cannot_prove_a_selected_item_price(label):
    message = f"Change valves so the {label} is €90."
    reject(saved(items=True), proposed(patches=[item_patch(message)]), message)


@pytest.mark.parametrize("path", ["initial", "replacement", "quantity"])
def test_collective_scope_also_constrains_creation_replacement_and_quantity(path):
    notes = saved(items=path != "initial")
    if path == "quantity":
        message = "Change valves quantity to 4 so the combined total is €100."
        proposal = proposed(patches=[item_patch(message, "4", field="quantity")])
    else:
        prefix = "Replace all line items with: " if path == "replacement" else ""
        message = prefix + "3 valves for a combined total of €90 and 2 elbows at €10."
        proposal = proposed(
            line_items=[{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
            line_items_evidence=message,
        )
    reject(notes, proposal, message)


@pytest.mark.parametrize(
    "field,value,assertion",
    [
        ("vat_rate", "23", "VAT 23%"),
        ("vat_basis", "inclusive", "including VAT"),
    ],
)
@pytest.mark.parametrize(
    "heading,marker",
    [
        ("*Which VAT treatment applies?*", "-"),
        ("**Which VAT treatment applies?**", "1."),
        ("# Which VAT treatment applies?", "> -"),
        ("> Which VAT treatment applies?", "-"),
        ("*VAT options:*", "1)"),
        ("**VAT options:**", "-"),
        ("> ### **Which VAT treatment applies?**", "(a)"),
        ("Which VAT treatment applies?", "-"),
    ],
)
def test_vat_heading_intent_survives_whatsapp_markdown_and_lists(
    field, value, assertion, heading, marker
):
    message = f"{heading}\n\n  {marker} {assertion}"
    reject(saved(vat=True), proposed((field, value, assertion)), message)


@pytest.mark.parametrize(
    "message,field,value,evidence",
    [
        (
            "Use VAT 23%; the old invoice is exempt, but now use VAT 0%.",
            "vat_rate",
            "23",
            "23%",
        ),
        (
            "Use VAT 23%; the old invoice is exempt, but this one is VAT 0%.",
            "vat_rate",
            "23",
            "23%",
        ),
        (
            "Use VAT 23%; the old invoice is exempt, but instead use VAT 0%.",
            "vat_rate",
            "23",
            "23%",
        ),
        (
            "Use VAT 23%; the old invoice is exempt, but this invoice is VAT 0%.",
            "vat_rate",
            "23",
            "23%",
        ),
        (
            "Use VAT 23%; the old invoice is exempt, but the new invoice is VAT 0%.",
            "vat_rate",
            "23",
            "23%",
        ),
        (
            "Use including VAT; the old invoice is exempt, but now use excluding VAT.",
            "vat_basis",
            "inclusive",
            "including VAT",
        ),
        (
            "Use including VAT; the old invoice is exempt, but this one is excluding VAT.",
            "vat_basis",
            "inclusive",
            "including VAT",
        ),
        (
            "Use including VAT; the old invoice is exempt, but instead use excluding VAT.",
            "vat_basis",
            "inclusive",
            "including VAT",
        ),
    ],
)
def test_historical_fact_does_not_hide_current_rate_or_basis_conflicts(
    message, field, value, evidence
):
    reject(saved(vat=True), proposed((field, value, evidence)), message)


@pytest.mark.parametrize(
    "continuation",
    [
        "; do not make this change.",
        "; actually cancel that.",
        ", or leave the invoice as is.",
        "; except keep valves unchanged.",
        "; keep this item unchanged.",
    ],
)
def test_full_message_cancellation_or_preservation_vetoes_an_item_patch(continuation):
    evidence = "Change valves unit price €30"
    reject(
        saved(items=True),
        proposed(patches=[item_patch(evidence)]),
        evidence + continuation,
    )


@pytest.mark.parametrize(
    "message",
    ["Set amount €500; no, cancel that.", "Set amount €500; do not make this change."],
)
def test_scalar_changes_cannot_ignore_a_later_cancellation(message):
    reject(saved(), proposed(("amount", "500", "Set amount €500")), message)


@pytest.mark.parametrize(
    "message,field,value,evidence",
    [
        ("Do not change customer name to Jack.", "customer_name", "Jack", "Jack"),
        (
            "Do not change work description to maintenance.",
            "work_description",
            "maintenance",
            "maintenance",
        ),
        (
            "Do not replace the address with 25 Main Street.",
            "customer_details",
            "25 Main Street",
            "25 Main Street",
        ),
        (
            "The previous invoice was for Jack; this invoice is for John.",
            "customer_name",
            "Jack",
            "Jack",
        ),
        (
            "The old invoice work description was maintenance; this invoice is for repairs.",
            "work_description",
            "maintenance",
            "maintenance",
        ),
        (
            "The previous invoice address is 25 Main Street; this invoice address is 1 Oak Road.",
            "customer_details",
            "25 Main Street",
            "25 Main Street",
        ),
        (
            "Customer name is Jack; work description is maintenance.",
            "customer_name",
            "maintenance",
            "maintenance",
        ),
        (
            "Customer name is Jack; work description is maintenance.",
            "work_description",
            "Jack",
            "Jack",
        ),
        (
            "Customer details are 25 Main Street; work description is maintenance.",
            "customer_details",
            "maintenance",
            "maintenance",
        ),
        (
            "Set customer name Jack; set customer name Una.",
            "customer_name",
            "Jack",
            "Set customer name Jack",
        ),
        (
            "Set work description maintenance; set work description installation.",
            "work_description",
            "maintenance",
            "Set work description maintenance",
        ),
    ],
)
def test_text_changes_require_current_affirmative_matching_field_authority(
    message, field, value, evidence
):
    reject(saved(), proposed((field, value, evidence)), message)


@pytest.mark.parametrize(
    "message,field,value,evidence",
    [
        ("Make it 500e, cheers", "amount", "500", "500e"),
        ("Make it 1.5k for the job", "amount", "1500", "1.5k"),
        ("500e, cheers", "amount", "500", "500e"),
        ("1.5k for the job", "amount", "1500", "1.5k"),
        ("Make it €500", "amount", "500", "€500"),
        ("Invoice John €500 for 3 hours work", "amount", "500", "€500"),
        ("Labour 500", "labour", "500", "500"),
        ("€100 for labour", "labour", "100", "€100"),
        ("Set labour €500", "labour", "500", "€500"),
        ("Materials cost €75.25", "materials", "75.25", "€75.25"),
        ("Set customer name Jack", "customer_name", "Jack", "Jack"),
        ("Set work description maintenance", "work_description", "maintenance", "maintenance"),
        (
            "Customer details: 25 Main Street",
            "customer_details",
            "25 Main Street",
            "25 Main Street",
        ),
        (
            "The previous invoice was for Jack; this invoice is for John Murphy.",
            "customer_name",
            "John Murphy",
            "John Murphy",
        ),
        ("*Use VAT 23%*", "vat_rate", "23", "23%"),
        ("**Use including VAT**", "vat_basis", "inclusive", "including VAT"),
    ],
)
def test_supported_affirmative_financial_and_customer_updates_remain_functional(
    message, field, value, evidence
):
    notes = saved(vat=field.startswith("vat_"))
    before = notes.model_dump()
    updated = apply_proposal(notes, proposed((field, value, evidence)), message)
    assert updated.model_dump() == {**before, field: value}
    assert notes.model_dump() == before


@pytest.mark.parametrize(
    "evidence",
    [
        "Change valves unit price €30 each",
        "Change valves line total €90",
        "Change valves overall price €90",
    ],
)
def test_supported_item_prices_survive_preservation_of_another_item(evidence):
    notes = saved(items=True)
    before = notes.model_dump()
    updated = apply_proposal(
        notes,
        proposed(patches=[item_patch(evidence)]),
        evidence + "; keep elbows unchanged.",
        expected_version=7,
        current_version=7,
    )
    assert updated.model_dump() == {
        **before,
        "line_items": [{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
    }
    assert notes.model_dump() == before


def test_item_bound_overall_total_retains_exact_decimal_product_support():
    message = "2 valves overall price €50.50"
    notes = InvoiceNotes(vat_basis="no_vat")
    proposal = proposed(
        line_items=[{"description": "valves", "quantity": "2", "unit_price": "25.25"}],
        line_items_evidence=message,
    )
    updated = apply_proposal(notes, proposal, message)
    assert updated.line_items[0].model_dump() == {
        "description": "valves",
        "quantity": "2",
        "unit_price": "25.25",
    }
    assert notes.model_dump() == InvoiceNotes(vat_basis="no_vat").model_dump()


def test_valid_and_invalid_changes_are_rejected_as_one_atomic_proposal():
    message = "Set labour €500; do not change customer name to Jack."
    reject(
        saved(),
        proposed(("labour", "500", "Set labour €500"), ("customer_name", "Jack", "Jack")),
        message,
    )
