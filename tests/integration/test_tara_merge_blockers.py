"""Merge-blocker probes cross signed ingress and restricted-role persistence."""

from copy import deepcopy

import pytest
from test_messaging import rows, verify_link
from test_tara import accept, make_worker, notes
from test_tara import messaging_client as _messaging_client
from test_tara_review_corrections import change, complete_notes, proposal, reply_body

from anoifig.tara.service import INVALID

messaging_client = _messaging_client
pytestmark = pytest.mark.integration
ITEMS = [
    {"description": "valves", "quantity": "3", "unit_price": "25"},
    {"description": "elbows", "quantity": "2", "unit_price": "10"},
]


def establish(client, database, seed, bearer, *, items=True):
    verify_link(client, seed, bearer)
    worker, ai = make_worker(client)
    complete_notes(worker, ai, client)
    message = "Use VAT rate 13.5%, excluding VAT."
    ai.results.append(
        proposal([change("vat_basis", "exclusive", message), change("vat_rate", "13.5", message)])
    )
    assert worker.process_delivery(accept(client, message))
    if items:
        message = "3 valves at €25 and 2 elbows at €10"
        ai.results.append(
            proposal(
                [], line_items=ITEMS, line_items_evidence=message, intent="invoice_preparation"
            )
        )
        assert worker.process_delivery(accept(client, message))
        assert notes(database)["line_items"] == ITEMS
    assert notes(database)["vat_basis"] == "exclusive"
    assert notes(database)["vat_rate"] == "13.5"
    return worker, ai


def patch(message, value, *, field="unit_price", evidence=None):
    return proposal(
        [],
        line_item_patches=[
            {
                "index": 0,
                "description": "valves",
                "evidence": message,
                "changes": [{"field": field, "value": value, "evidence": evidence or message}],
            }
        ],
    )


def assert_rejected(database, identifier, before):
    state = rows(database, "tara_states")[0]
    assert state["notes"] == before["notes"]
    assert state["version"] == before["version"]
    assert state["pending_clarification"] is None
    body = reply_body(database, identifier)
    assert body == INVALID
    assert "?" in body
    assert "Updated that." not in body
    assert "information is saved for preparation" not in body
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["status"] == "complete"
    assert run["error_code"] == "invalid_model_response"
    assert run["action"] is None


@pytest.mark.parametrize(
    "message",
    [
        "3 valves for a total price of €75",
        "3 valves subtotal cost €75",
        "3 valves overall price at €75",
        "3 valves at €75 total",
        "3 valves for a total price of €100",
    ],
)
def test_line_total_cannot_be_saved_as_unit_price(
    message, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer, items=False)
    before = rows(database, "tara_states")[0]
    value = "100" if "100" in message else "75"
    ai.results.append(
        proposal(
            [],
            line_items=[{"description": "valves", "quantity": "3", "unit_price": value}],
            line_items_evidence=message,
            intent="invoice_preparation",
        )
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)


@pytest.mark.parametrize(
    "message,value",
    [
        ("Make valves total price €75", "75"),
        ("Make valves overall cost €75", "75"),
        ("Make valves subtotal at €75", "75"),
        ("Make valves total price €100", "33.33"),
        ("Make valves quantity 5 for a total price €75", "5"),
        ("Make valves price €25 with washers at 10", "10"),
    ],
)
def test_ambiguous_corrections_preserve_every_existing_item(
    message, value, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = rows(database, "tara_states")[0]
    ai.results.append(
        patch(message, value, field="quantity" if "quantity" in message else "unit_price")
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)
    assert notes(database)["line_items"] == ITEMS


@pytest.mark.parametrize("connector", ["with", "plus", "and", "&"])
@pytest.mark.parametrize("prices", [("€25", "10"), ("25", "€10"), ("25", "10")])
def test_an_omitted_items_price_cannot_be_borrowed(
    connector, prices, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer, items=False)
    before = rows(database, "tara_states")[0]
    message = f"3 valves at {prices[0]} {connector} elbows at {prices[1]}"
    ai.results.append(
        proposal(
            [],
            line_items=[{"description": "valves", "quantity": "3", "unit_price": "10"}],
            line_items_evidence=message,
            intent="invoice_preparation",
        )
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)


@pytest.mark.parametrize("price", ["25", "30"])
def test_conflicting_repeated_item_clauses_cannot_choose_a_price(
    price, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer, items=False)
    before = rows(database, "tara_states")[0]
    message = "3 valves at €25; 3 valves at €30"
    ai.results.append(
        proposal(
            [],
            line_items=[{"description": "valves", "quantity": "3", "unit_price": price}],
            line_items_evidence=message,
            intent="invoice_preparation",
        )
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)


@pytest.mark.parametrize("evidence", ["23%", None], ids=["cropped", "complete"])
@pytest.mark.parametrize(
    "message",
    [
        "VAT 23% or VAT exempt",
        "VAT 23% or exempt",
        "VAT 23% versus zero-rated",
        "VAT 23% / VAT exempt",
        "VAT 23%, alternatively exempt",
        "Should VAT be 23% or exempt?",
        "VAT 23% or no VAT",
        "VAT 23% or\nVAT exempt",
        "Use VAT exempt instead of VAT 23%.",
        "VAT 23%, VAT exempt",
        "VAT 23% and zero-rated",
    ],
)
def test_unresolved_vat_treatments_preserve_prior_vat_fields(
    evidence, message, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = rows(database, "tara_states")[0]
    ai.results.append(proposal([change("vat_rate", "23", evidence or message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)
    assert notes(database)["vat_rate"] == "13.5"
    assert notes(database)["vat_basis"] == "exclusive"
    assert notes(database)["line_items"] == ITEMS


@pytest.mark.parametrize(
    "message",
    [
        "VAT exempt / 23% VAT",
        "Use VAT 23% instead of VAT exempt.",
        "VAT exempt and zero-rated",
    ],
)
def test_treatment_comparisons_cannot_overwrite_basis(
    message, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = rows(database, "tara_states")[0]
    ai.results.append(proposal([change("vat_basis", "no_vat", message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)


@pytest.mark.parametrize(
    "message,value",
    [
        ("Make valves unit price €30 each", "30"),
        ("Make valves €30 apiece", "30"),
        ("Make valves price per unit €30", "30"),
        ("Make valves total price €90", "30"),
    ],
)
def test_supported_unit_updates_preserve_quantity_other_items_and_vat(
    message, value, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = notes(database)
    ai.results.append(patch(message, value))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    expected = deepcopy(before)
    expected["line_items"][0]["unit_price"] = value
    assert notes(database) == expected
    assert "Updated that." in reply_body(database, identifier)


@pytest.mark.parametrize("message,value", [("Use VAT 23%.", "23"), ("Use VAT rate 0%.", "0")])
def test_affirmative_numeric_vat_updates_do_not_change_treatment(
    message, value, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = notes(database)
    ai.results.append(proposal([change("vat_rate", value, message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert notes(database) == {**before, "vat_rate": value}
    assert notes(database)["vat_basis"] == "exclusive"
    assert "Updated that." in reply_body(database, identifier)


@pytest.mark.parametrize(
    "message,items",
    [
        ("3 valves for a total price of €75", [ITEMS[0]]),
        ("3 valves at €25 with 2 elbows at 10", ITEMS),
        ("3 valves at 25 plus 2 elbows at €10", ITEMS),
        ("a total of 3 valves at €25 each", [ITEMS[0]]),
    ],
)
def test_initial_items_keep_their_own_exact_quantity_and_price(
    message, items, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer, items=False)
    before = notes(database)
    ai.results.append(
        proposal([], line_items=items, line_items_evidence=message, intent="invoice_preparation")
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert notes(database) == {**before, "line_items": items}
    assert "information is saved for preparation" in reply_body(database, identifier)
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["action"] == "notes_merged"
    assert run["error_code"] is None
