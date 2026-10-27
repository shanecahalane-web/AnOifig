"""Supplemental role/authority variants use the same signed and restricted path."""

from copy import deepcopy

import pytest
from test_messaging import verify_link
from test_tara import accept, make_worker
from test_tara import messaging_client as _messaging_client
from test_tara_authority_persistence import (
    assert_accepted,
    assert_rejected,
    establish_complete,
    item_patch,
    saved_state,
)
from test_tara_review_corrections import change, proposal

messaging_client = _messaging_client
pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Price 3 valves.", "amount", "3"),
        ("Materials cost 3 valves.", "materials", "3"),
        ("Invoice reference EUR 500.", "amount", "500"),
        ("Reference number: EUR 500.", "amount", "500"),
        ("The address is EUR 25 Main Street.", "amount", "25"),
        ("Labour €8 per hour.", "labour", "8"),
        ("Materials price €200.", "amount", "200"),
        ("Materials amount €200.", "amount", "200"),
        ("Materials subtotal €200.", "amount", "200"),
        ("Labour total €500.", "amount", "500"),
        ("Total labour €500.", "amount", "500"),
    ],
)
def test_scalar_role_variants_preserve_complete_saved_state(
    message, field, value, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, scalar=True)
    before = saved_state(database)
    ai.results.append(proposal([change(field, value, value)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


def test_hourly_rate_is_not_an_item_unit_price(messaging_client, database, seed, bearer):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    message = "Change valves unit price €8 per hour."
    ai.results.append(proposal([], line_item_patches=[item_patch(message, value="8")]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Materials price €200.", "materials", "200"),
        ("Materials amount €200.", "materials", "200"),
        ("Materials subtotal €200.", "materials", "200"),
        ("Materials cost €200.", "materials", "200"),
        ("Labour total €500.", "labour", "500"),
        ("Total labour €500.", "labour", "500"),
        ("€500 for labour.", "labour", "500"),
        ("Price €3.", "amount", "3"),
        ("Labour 500.", "labour", "500"),
    ],
)
def test_specific_charge_labels_keep_their_own_field_and_other_values(
    message, field, value, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, scalar=True)
    before = saved_state(database)
    ai.results.append(proposal([change(field, value, message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_accepted(database, identifier, before, {**before["notes"], field: value})


@pytest.mark.parametrize("quote", ['"', "'", "“"])
def test_historical_quotation_cannot_supply_current_vat(
    quote, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, vat=True)
    before = saved_state(database)
    close = "”" if quote == "“" else quote
    message = f"The old invoice says {quote}now use VAT 23%{close}."
    ai.results.append(proposal([change("vat_rate", "23", "23%")]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize(
    "message,field,value",
    [
        (
            "Set work description customer requested repairs.",
            "work_description",
            "customer requested repairs",
        ),
        ("Set customer name Customer Care Limited.", "customer_name", "Customer Care Limited"),
    ],
)
def test_supplied_text_can_contain_customer_words(
    message, field, value, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    ai.results.append(proposal([change(field, value, value)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_accepted(database, identifier, before, {**before["notes"], field: value})


def test_implicit_invoice_customers_cannot_contradict_each_other(
    messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    message = "Invoice John for repairs; invoice Mary for repairs."
    ai.results.append(proposal([change("customer_name", "John", "John")]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


def test_document_qualified_other_item_preservation_keeps_valid_price_update(
    messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    evidence = "Change valves unit price €30 each"
    message = evidence + "; leave elbows unchanged on this invoice."
    ai.results.append(proposal([], line_item_patches=[item_patch(evidence)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    expected = deepcopy(before["notes"])
    expected["line_items"][0]["unit_price"] = "30"
    assert_accepted(database, identifier, before, expected)


@pytest.mark.parametrize(
    "continuation", ["do not ever apply that change.", "don't you make this change."]
)
def test_cancellation_modifiers_preserve_complete_notes(
    continuation, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    evidence = "Change valves unit price €30 each"
    ai.results.append(proposal([], line_item_patches=[item_patch(evidence)]))
    identifier = accept(messaging_client, evidence + "; " + continuation)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize("cropped", [False, True])
def test_customer_question_does_not_confirm_a_listed_name(
    cropped, messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    initial = "Set amount €600; labour €400; materials €200; no VAT"
    ai.results.append(
        proposal(
            [
                change("amount", "600", "Set amount €600"),
                change("labour", "400", "labour €400"),
                change("materials", "200", "materials €200"),
                change("vat_basis", "no_vat", "no VAT"),
            ],
            intent="invoice_preparation",
        )
    )
    assert worker.process_delivery(accept(messaging_client, initial))
    before = saved_state(database)
    assert before["notes"]["customer_name"] is None
    assert before["notes"]["amount"] == "600"
    message = "*Who should we invoice?*\n- Jack"
    ai.results.append(proposal([change("customer_name", "Jack", "Jack" if cropped else message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)
