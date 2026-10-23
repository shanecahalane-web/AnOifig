"""Document headings retain scope independently of a listed assertion's intent."""

import pytest

from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal


def proposed(field, value, evidence):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [{"field": field, "value": value, "evidence": evidence}],
            "line_items": None,
            "line_items_evidence": None,
        }
    )


@pytest.mark.parametrize(
    "heading,separator,marker",
    [
        ("The old invoice:", "\n", "- "),
        ("The old invoice had these charges:", "\n", "- "),
        ("The previous invoice:", "\n\n  ", "* "),
        ("The last job:", "\n", "1. "),
        ("The earlier bill:", "\n", "b. "),
        ("The old invoice:", "; ", "(a) "),
        ("The old invoice:", "; \n\n  ", "• "),
    ],
)
@pytest.mark.parametrize(
    "field,value,assertion", [("vat_rate", "23", "VAT 23%"), ("amount", "500", "amount €500")]
)
@pytest.mark.parametrize("cropped", [False, True])
def test_historical_document_lists_cannot_overwrite_current_fields(
    heading, separator, marker, field, value, assertion, cropped
):
    message = heading + separator + marker + assertion
    original = InvoiceNotes(amount="450", vat_basis="exclusive", vat_rate="13.5")
    before = original.model_dump()
    evidence = value if cropped else message
    with pytest.raises(ValueError):
        apply_proposal(original, proposed(field, value, evidence), message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "current",
    ["this invoice", "the current invoice", "the new invoice", "the invoice being prepared"],
)
@pytest.mark.parametrize(
    "field,value,assertion",
    [("vat_rate", "23", "use VAT 23%"), ("amount", "500", "set amount €500")],
)
def test_an_explicit_current_instruction_ends_a_historical_document_heading(
    current, field, value, assertion
):
    historical = "VAT 13.5%" if field == "vat_rate" else "amount €450"
    message = f"The old invoice:\n- {historical}\nFor {current}, {assertion}"
    original = InvoiceNotes(amount="450", vat_basis="exclusive", vat_rate="13.5")
    updated = apply_proposal(original, proposed(field, value, assertion), message)
    assert updated.model_dump() == {**original.model_dump(), field: value}


@pytest.mark.parametrize(
    "field,value,assertion",
    [("vat_rate", "23", "Use VAT 23%"), ("amount", "500", "Set amount €500")],
)
def test_a_completed_historical_statement_does_not_start_a_document_heading(
    field, value, assertion
):
    message = f"The old invoice was exempt.\n{assertion}"
    original = InvoiceNotes(amount="450", vat_basis="exclusive", vat_rate="13.5")
    updated = apply_proposal(original, proposed(field, value, assertion), message)
    assert updated.model_dump() == {**original.model_dump(), field: value}


@pytest.mark.parametrize(
    "heading,intent",
    [
        ("The old invoice:", "affirmative"),
        ("Which VAT applied on the old invoice?", "question"),
    ],
)
def test_document_headings_preserve_source_coordinates_and_independent_intent(heading, intent):
    from anoifig.tara.assertions import AssertionIntent, DocumentScope, assertion_context

    message = f"Seán's notes.\n{heading}\n\n  - VAT 23%"
    start = message.index("VAT 23%")
    context = assertion_context(message, start, start + len("VAT 23%"), topic="vat")
    assert context.expression == message[context.start : context.end] == "VAT 23%"
    assert context.start == start
    assert context.clause_start <= context.start < context.end <= context.clause_end
    assert context.document_scope == DocumentScope.HISTORICAL
    assert context.intent == AssertionIntent(intent)
    assert context.document_heading_start is not None
    assert message[context.document_heading_start :].lstrip().startswith(heading)


def test_current_document_heading_is_not_a_question_or_an_option():
    from anoifig.tara.assertions import AssertionIntent, DocumentScope, assertion_context

    message = "This invoice:\n- amount €500"
    start = message.index("500")
    context = assertion_context(message, start, start + 3)
    assert context.document_scope == DocumentScope.CURRENT
    assert context.intent == AssertionIntent.AFFIRMATIVE
    assert context.document_heading_start == 0


def test_current_document_reset_also_owns_following_list_continuations():
    message = "The old invoice:\n- VAT 0%\nFor this invoice use VAT 23%\n- including VAT"
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5")
    updated = apply_proposal(original, proposed("vat_basis", "inclusive", "including VAT"), message)
    assert updated.vat_basis == "inclusive"
    assert updated.vat_rate == original.vat_rate
