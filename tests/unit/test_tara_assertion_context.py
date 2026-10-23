"""Shared contexts retain source coordinates, intent and document references."""

import pytest

from anoifig.tara.assertions import AssertionIntent, DocumentScope, assertion_context
from anoifig.tara.schemas import InvoiceNotes, ProposedNotes, apply_proposal, current_vat_assertions


@pytest.mark.parametrize(
    "message,expression,intent,scope",
    [
        ("Use VAT 23%", "VAT 23%", "affirmative", "current"),
        ("Seán: use VAT 23%", "VAT 23%", "affirmative", "current"),
        ("Should I use VAT 23%", "VAT 23%", "question", "current"),
        ("VAT 23%, is that correct?", "VAT 23%", "question", "current"),
        ("Do not use VAT 23%", "VAT 23%", "negated", "current"),
        ("VAT 23% is incorrect", "VAT 23%", "negated", "current"),
        ("If VAT 23% applies", "VAT 23%", "conditional", "current"),
        ("Maybe VAT 23%", "VAT 23%", "ambiguous", "current"),
        ("No VAT, not registered.", "No VAT", "affirmative", "current"),
        ("Not registered for VAT", "Not registered for VAT", "affirmative", "current"),
        ("The old invoice is VAT 23%", "VAT 23%", "affirmative", "historical"),
        ("Is the old invoice VAT 23%?", "VAT 23%", "question", "historical"),
        (
            "The old invoice is exempt, but this invoice is VAT 23%",
            "VAT 23%",
            "affirmative",
            "current",
        ),
        (
            "The old invoice was not registered, but this invoice uses VAT 23%",
            "VAT 23%",
            "affirmative",
            "current",
        ),
        (
            "The old invoice was not VAT registered, but this invoice uses VAT 23%",
            "VAT 23%",
            "affirmative",
            "current",
        ),
        (
            "If the old invoice was exempt, but this invoice uses VAT 23%",
            "VAT 23%",
            "conditional",
            "current",
        ),
        (
            "Which VAT applies?\n- VAT 23%\nThis invoice is for John.\n- VAT 0%",
            "VAT 0%",
            "question",
            "current",
        ),
        (
            "Which VAT applies?\n- VAT 23%\nThis invoice is about VAT.\n- VAT 0%",
            "VAT 0%",
            "question",
            "current",
        ),
        (
            "Which VAT applies?\n- VAT 23%\nThis invoice uses VAT if registered.\n- VAT 0%",
            "VAT 0%",
            "question",
            "current",
        ),
        (
            "VAT options:\n- For this invoice use VAT 23%",
            "VAT 23%",
            "option",
            "current",
        ),
        (
            "VAT options:\n1. This invoice is VAT 23%",
            "VAT 23%",
            "option",
            "current",
        ),
        (
            "VAT options:\nVAT 23%\nFor this invoice, use VAT 0%",
            "VAT 0%",
            "affirmative",
            "current",
        ),
    ],
)
def test_context_preserves_independent_intent_scope_and_source(message, expression, intent, scope):
    start = message.index(expression)
    context = assertion_context(message, start, start + len(expression), topic="vat")
    assert context.expression == expression == message[context.start : context.end]
    assert context.start == start
    assert context.end == start + len(expression)
    assert context.clause_start <= context.start < context.end <= context.clause_end
    assert context.intent == AssertionIntent(intent)
    assert context.document_scope == DocumentScope(scope)


@pytest.mark.parametrize(
    "historical",
    ["The old invoice was not VAT registered", "The old invoice was not registered"],
)
def test_a_clear_current_vat_statement_does_not_inherit_historical_negation(historical):
    message = historical + ", but this invoice uses VAT 23%"
    proposal = ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [{"field": "vat_rate", "value": "23", "evidence": "23%"}],
            "line_items": None,
            "line_items_evidence": None,
        }
    )
    assert apply_proposal(InvoiceNotes(vat_basis="exclusive"), proposal, message).vat_rate == "23"


def test_a_scoped_heading_reset_keeps_all_genuinely_affirmative_facts():
    message = "VAT options:\nVAT 13.5%\nFor this invoice, use VAT 23%; this invoice is VAT 0%"
    assert [(part.rate, part.context.intent) for part in current_vat_assertions(message)] == [
        (23, AssertionIntent.AFFIRMATIVE),
        (0, AssertionIntent.AFFIRMATIVE),
    ]


@pytest.mark.parametrize("start,end", [(-1, 1), (0, 0), (1, 0), (0, 99)])
def test_invalid_source_spans_are_rejected(start, end):
    with pytest.raises(ValueError):
        assertion_context("VAT 23%", start, end)
