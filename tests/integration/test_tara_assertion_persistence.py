"""Assertion-boundary regressions traverse signed ingress and restricted RLS."""

from copy import deepcopy

import pytest
from sqlalchemy import text
from test_messaging import OTHER_PHONE, rows, set_context, verify_link
from test_tara import accept, notes
from test_tara import messaging_client as _messaging_client
from test_tara_review_corrections import change, proposal, reply_body
from test_tara_scope_persistence import establish, set_vat

from anoifig.tara.service import INVALID

messaging_client = _messaging_client
pytestmark = pytest.mark.integration
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


def patch(message, value="30", *, field="unit_price", evidence=None):
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


def assert_controlled_rejection(database, identifier, before):
    state = next(row for row in rows(database, "tara_states") if row["id"] == before["id"])
    assert state["notes"] == before["notes"]
    assert state["version"] == before["version"]
    assert state["pending_clarification"] == before["pending_clarification"]
    replies = rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})
    assert len(replies) == 1
    assert reply_body(database, identifier) == INVALID
    assert "?" in replies[0]["body"]
    assert "Updated that." not in replies[0]["body"]
    assert "information is saved for preparation" not in replies[0]["body"]
    runs = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})
    assert len(runs) == 1
    assert runs[0]["status"] == "complete"
    assert runs[0]["action"] is None
    assert runs[0]["error_code"] == "invalid_model_response"


def assert_accepted(database, identifier, before, expected, *, initial=False):
    assert notes(database) == expected
    assert rows(database, "tara_states")[0]["version"] == before["version"] + 1
    body = reply_body(database, identifier)
    assert ("information is saved for preparation" if initial else "Updated that.") in body
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["status"] == "complete"
    assert run["action"] == "notes_merged"
    assert run["error_code"] is None


@pytest.mark.parametrize("label", AGGREGATE_LABELS)
@pytest.mark.parametrize("path", ["initial", "replacement", "price-patch", "quantity-patch"])
def test_aggregate_scope_rejections_preserve_complete_notes_on_every_item_write_path(
    label, path, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer, items=path != "initial")
    before = rows(database, "tara_states")[0]
    if path in {"initial", "replacement"}:
        prefix = "Replace all line items with: " if path == "replacement" else ""
        message = f"{prefix}3 valves for a {label} of €90 and 2 elbows at €10"
        ai.results.append(
            proposal(
                [],
                line_items=[{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
                line_items_evidence=message,
                intent="invoice_preparation",
            )
        )
    elif path == "quantity-patch":
        message = f"Change valves quantity to 4 so the {label} is €100"
        ai.results.append(patch(message, "4", field="quantity"))
    else:
        message = f"Change valves so the {label} is €90"
        ai.results.append(patch(message))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_controlled_rejection(database, identifier, before)


def test_cropped_aggregate_evidence_cannot_allocate_or_acknowledge_a_price_change(
    messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = rows(database, "tara_states")[0]
    message = "Change valves so the total for all the items is €90"
    ai.results.append(patch(message, evidence="€90"))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_controlled_rejection(database, identifier, before)


@pytest.mark.parametrize("label", AGGREGATE_LABELS)
@pytest.mark.parametrize("total,accepted", [("90", False), ("110", True)])
def test_stated_unit_prices_check_aggregate_amount_against_both_saved_items(
    label, total, accepted, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = rows(database, "tara_states")[0]
    message = f"Make valves unit price €30 each; {label} €{total}"
    ai.results.append(patch("Make valves unit price €30 each"))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    if accepted:
        expected = deepcopy(before["notes"])
        expected["line_items"][0]["unit_price"] = "30"
        assert_accepted(database, identifier, before, expected)
    else:
        assert_controlled_rejection(database, identifier, before)


@pytest.mark.parametrize("message,field,value,evidence", VAT_LISTS)
@pytest.mark.parametrize("cropped", [False, True])
def test_formatted_vat_question_replies_do_not_overwrite_either_saved_vat_field(
    message, field, value, evidence, cropped, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    set_vat(worker, ai, messaging_client)
    before = rows(database, "tara_states")[0]
    ai.results.append(proposal([change(field, value, evidence if cropped else message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_controlled_rejection(database, identifier, before)


@pytest.mark.parametrize("historical,current", HISTORICAL_CURRENT)
@pytest.mark.parametrize("field", ["vat_rate", "vat_basis"])
@pytest.mark.parametrize("cropped", [False, True])
def test_a_historical_document_cannot_hide_a_conflicting_current_invoice_assertion(
    historical, current, field, cropped, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    set_vat(worker, ai, messaging_client)
    before = rows(database, "tara_states")[0]
    if field == "vat_rate":
        message = f"Use VAT 23%; {historical} is exempt, but {current} is VAT 0%"
        value, evidence = "23", "23%"
    else:
        message = f"Use including VAT; {historical} is exempt, but {current} is excluding VAT"
        value, evidence = "inclusive", "including VAT"
    ai.results.append(proposal([change(field, value, evidence if cropped else message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_controlled_rejection(database, identifier, before)


@pytest.mark.parametrize(
    "message",
    [
        "Make valves unit price €30 each",
        "Make valves line total €90",
        "Make valves overall price €90",
    ],
)
def test_explicit_unit_and_item_bound_total_updates_keep_other_notes(
    message, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = rows(database, "tara_states")[0]
    ai.results.append(patch(message))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    expected = deepcopy(before["notes"])
    expected["line_items"][0]["unit_price"] = "30"
    assert_accepted(database, identifier, before, expected)


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
def test_affirmative_vat_updates_keep_unrelated_historical_document_context(
    message, changes, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    set_vat(worker, ai, messaging_client)
    before = rows(database, "tara_states")[0]
    ai.results.append(proposal([change(field, value, message) for field, value in changes]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_accepted(database, identifier, before, {**before["notes"], **dict(changes)})


@pytest.mark.parametrize("finding", ["aggregate", "vat-list", "historical-current"])
def test_assertion_rejections_preserve_tenant_b_and_retain_raw_rls_enforcement(
    finding, messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    set_vat(worker, ai, messaging_client)
    before = rows(database, "tara_states")[0]
    verify_link(messaging_client, seed, bearer, phone=OTHER_PHONE, tenant="b", subject="owner-b")
    other_message = "Invoice Una €700 for repairs; no VAT."
    ai.results.append(
        proposal(
            [
                change("customer_name", "Una", other_message),
                change("amount", "700", other_message),
                change("work_description", "repairs", other_message),
                change("vat_basis", "no_vat", other_message),
            ],
            intent="invoice_preparation",
        )
    )
    assert worker.process_delivery(accept(messaging_client, other_message, phone=OTHER_PHONE))
    other = next(
        row for row in rows(database, "tara_states") if row["tenant_id"] == seed.businesses["b"]
    )
    if finding == "aggregate":
        message = "Change valves so the total for all the items is €90"
        ai.results.append(patch(message))
    else:
        message = (
            "Which VAT treatment applies?\n- VAT 23%"
            if finding == "vat-list"
            else "Use VAT 23%; the old invoice is exempt, but this invoice is VAT 0%"
        )
        ai.results.append(proposal([change("vat_rate", "23", "23%")]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_controlled_rejection(database, identifier, before)
    assert (
        next(
            row for row in rows(database, "tara_states") if row["tenant_id"] == seed.businesses["b"]
        )
        == other
    )
    with database.runtime.begin() as connection:
        set_context(connection, seed, subject="owner-b", tenant="b")
        assert (
            connection.execute(
                text("SELECT count(*) FROM tara_states WHERE tenant_id = :id"),
                {"id": seed.businesses["a"]},
            ).scalar_one()
            == 0
        )
        result = connection.execute(
            text("UPDATE tara_states SET version = version + 1 WHERE tenant_id = :id"),
            {"id": seed.businesses["a"]},
        )
        assert result.rowcount == 0
    assert (
        next(
            row for row in rows(database, "tara_states") if row["tenant_id"] == seed.businesses["b"]
        )
        == other
    )
