"""Shared source invariants remain atomic through signed ingress and real RLS."""

from copy import deepcopy

import pytest
from sqlalchemy import text
from test_messaging import OTHER_PHONE, rows, set_context, verify_link
from test_tara import accept
from test_tara import messaging_client as _messaging_client
from test_tara_assertion_persistence import assert_controlled_rejection
from test_tara_review_corrections import change, proposal, reply_body
from test_tara_scope_persistence import establish, set_vat

messaging_client = _messaging_client
pytestmark = pytest.mark.integration


def prepare(client, database, seed, bearer):
    worker, ai = establish(client, database, seed, bearer)
    set_vat(worker, ai, client)
    message = "Amount €450; labour €100; materials €350"
    ai.results.append(
        proposal(
            [
                change(field, value, message)
                for field, value in [("amount", "450"), ("labour", "100"), ("materials", "350")]
            ]
        )
    )
    assert worker.process_delivery(accept(client, message))
    before = rows(database, "tara_states")[0]
    assert before["notes"]["amount"] == "450"
    verify_link(client, seed, bearer, phone=OTHER_PHONE, tenant="b", subject="owner-b")
    message = "Invoice Una €700 for repairs; no VAT."
    ai.results.append(
        proposal(
            [
                change("customer_name", "Una", message),
                change("amount", "700", message),
                change("vat_basis", "no_vat", message),
            ],
            intent="invoice_preparation",
        )
    )
    assert worker.process_delivery(accept(client, message, phone=OTHER_PHONE))
    other = dict(
        next(
            row for row in rows(database, "tara_states") if row["tenant_id"] == seed.businesses["b"]
        )
    )
    return worker, ai, before, other


def assert_other_tenant(database, seed, other):
    assert (
        dict(
            next(
                row
                for row in rows(database, "tara_states")
                if row["tenant_id"] == seed.businesses["b"]
            )
        )
        == other
    )
    with database.runtime.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM tara_states")) == 0
        set_context(connection, seed, tenant="b", subject="owner-b")
        assert (
            connection.scalar(
                text("SELECT count(*) FROM tara_states WHERE tenant_id=:id"),
                {"id": seed.businesses["a"]},
            )
            == 0
        )
        assert (
            connection.execute(
                text("UPDATE tara_states SET version=version+1 WHERE tenant_id=:id"),
                {"id": seed.businesses["a"]},
            ).rowcount
            == 0
        )


@pytest.mark.parametrize(
    "field,value,assertion",
    [
        ("amount", "500", "amount €500"),
        ("vat_rate", "23", "VAT 23%"),
        ("vat_basis", "inclusive", "including VAT"),
    ],
)
def test_historical_document_lists_never_mutate_current_notes(
    field, value, assertion, messaging_client, database, seed, bearer
):
    worker, ai, before, other = prepare(messaging_client, database, seed, bearer)
    message = f"The old invoice:\n- {assertion}"
    ai.results.append(proposal([change(field, value, assertion)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_controlled_rejection(database, identifier, before)
    assert_other_tenant(database, seed, other)


@pytest.mark.parametrize("field", ["amount", "labour", "materials"])
def test_conflicting_scalar_assertions_preserve_complete_persisted_state(
    field, messaging_client, database, seed, bearer
):
    worker, ai, before, other = prepare(messaging_client, database, seed, bearer)
    evidence = f"Set {field} €500"
    message = evidence + f"; {field} €600"
    ai.results.append(proposal([change(field, "500", evidence)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_controlled_rejection(database, identifier, before)
    assert_other_tenant(database, seed, other)


@pytest.mark.parametrize("label", ["total", "for this invoice, total"])
@pytest.mark.parametrize("total,accepted", [("90", False), ("110", True)])
def test_an_unbound_total_checks_every_final_item(
    label, total, accepted, messaging_client, database, seed, bearer
):
    # This setup has no tax or overlapping scalar charges, so the sum is exact.
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = rows(database, "tara_states")[0]
    evidence = "Make valves unit price €30 each"
    message = evidence + f"; {label} €{total}"
    ai.results.append(
        proposal(
            [],
            line_item_patches=[
                {
                    "index": 0,
                    "description": "valves",
                    "evidence": evidence,
                    "changes": [{"field": "unit_price", "value": "30", "evidence": evidence}],
                }
            ],
        )
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    if not accepted:
        assert_controlled_rejection(database, identifier, before)
    else:
        after = rows(database, "tara_states")[0]
        expected = deepcopy(before["notes"])
        expected["line_items"][0]["unit_price"] = "30"
        assert after["notes"] == expected
        assert after["version"] == before["version"] + 1
        assert "Updated that." in reply_body(database, identifier)
        run = rows(database, "tara_runs", "WHERE message_id=:id", {"id": identifier})[0]
        assert run["action"] == "notes_merged" and run["error_code"] is None


@pytest.mark.parametrize(
    "field,value,assertion",
    [
        ("amount", "500", "set amount €500"),
        ("vat_rate", "23", "use VAT 23%"),
        ("vat_basis", "inclusive", "use including VAT"),
    ],
)
def test_an_explicit_current_document_instruction_can_follow_a_historical_list(
    field, value, assertion, messaging_client, database, seed, bearer
):
    worker, ai, before, other = prepare(messaging_client, database, seed, bearer)
    message = f"The old invoice:\n- VAT 0%\nFor this invoice, {assertion}"
    ai.results.append(proposal([change(field, value, assertion)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    after = next(
        row
        for row in rows(database, "tara_states")
        if row["conversation_id"] == before["conversation_id"]
    )
    assert after["notes"] == {**before["notes"], field: value}
    assert after["version"] == before["version"] + 1
    assert "Updated that." in reply_body(database, identifier)
    run = rows(database, "tara_runs", "WHERE message_id=:id", {"id": identifier})[0]
    assert run["action"] == "notes_merged" and run["error_code"] is None
    assert_other_tenant(database, seed, other)
