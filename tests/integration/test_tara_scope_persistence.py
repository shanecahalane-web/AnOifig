"""Scope rejections traverse signed ingress, actual runtime RLS and durable replies."""

from copy import deepcopy

import pytest
from sqlalchemy import text
from test_messaging import OTHER_PHONE, rows, set_context, verify_link
from test_tara import accept, make_worker, notes
from test_tara import messaging_client as _messaging_client
from test_tara_merge_blockers import assert_rejected, patch
from test_tara_review_corrections import change, proposal, reply_body

from anoifig.tara.service import INVALID

messaging_client = _messaging_client
pytestmark = pytest.mark.integration
ITEMS = [
    {"description": "valves", "quantity": "3", "unit_price": "25"},
    {"description": "elbows", "quantity": "2", "unit_price": "10"},
]
TOTAL_LABELS = [
    "overall invoice total",
    "invoice total",
    "grand total",
    "total for the invoice",
    "invoice subtotal",
    "overall total",
    "total for all items",
    "whole bill total",
    "invoice amount",
    "whole invoice price",
    "price for the entire invoice",
    "grand cost",
    "invoice net total",
    "invoice final total",
    "total due for the invoice",
    "total for both items",
    "invoice gross total",
    "net total of this invoice",
    "whole invoice",
    "entire bill",
]
VAT_CHOICES = [
    "VAT options:\nVAT 23%",
    "Choose VAT treatment:\nVAT 23%",
    "Which VAT treatment applies?\nVAT 23%",
    "VAT options:\nVAT 23%\nexcluding VAT",
    "VAT options:\nVAT exempt\nVAT 23%",
    "Choose VAT treatment:\nVAT exempt\nVAT 23%",
    "Either:\nVAT exempt\nVAT 23%",
    "VAT 23%\nNo VAT",
    "VAT 23%\nZero-rated",
    "VAT 23%; VAT exempt",
    "VAT options:\n- VAT exempt\n- VAT 23%",
    "VAT 23%; including VAT; VAT exempt",
]


def establish(client, database, seed, bearer, *, items=True):
    verify_link(client, seed, bearer)
    worker, ai = make_worker(client)
    message = "Invoice John for repairs: 3 valves at €25 and 2 elbows at €10; no VAT."
    ai.results.append(
        proposal(
            [
                change("customer_name", "John", message),
                change("work_description", "repairs", message),
                change("vat_basis", "no_vat", message),
            ],
            intent="invoice_preparation",
            line_items=ITEMS if items else None,
            line_items_evidence=message if items else None,
        )
    )
    assert worker.process_delivery(accept(client, message))
    assert notes(database)["amount"] is None
    assert notes(database)["line_items"] == (ITEMS if items else [])
    return worker, ai


def set_vat(worker, ai, client):
    message = "Use VAT rate 13.5%, excluding VAT."
    ai.results.append(
        proposal([change("vat_basis", "exclusive", message), change("vat_rate", "13.5", message)])
    )
    assert worker.process_delivery(accept(client, message))


@pytest.mark.parametrize("label", TOTAL_LABELS)
@pytest.mark.parametrize("initial", [False, True])
def test_invoice_scope_never_becomes_a_line_total(
    label,
    initial,
    messaging_client,
    database,
    seed,
    bearer,
):
    worker, ai = establish(messaging_client, database, seed, bearer, items=not initial)
    before = rows(database, "tara_states")[0]
    if initial:
        message = f"3 valves for an {label} of €90 and 2 elbows at €10."
        ai.results.append(
            proposal(
                [],
                line_items=[{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
                line_items_evidence=message,
                intent="invoice_preparation",
            )
        )
    else:
        message = f"Change valves so the {label} is €90."
        ai.results.append(patch(message, "30"))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)
    assert len(rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})) == 1


@pytest.mark.parametrize("total,accepted", [("90", False), ("110", True)])
@pytest.mark.parametrize(
    "label",
    [
        "invoice total",
        "invoice net total",
        "total due for the invoice",
        "total for both items",
        "whole invoice",
    ],
)
def test_full_invoice_consistency_does_not_allocate_or_round(
    total,
    accepted,
    label,
    messaging_client,
    database,
    seed,
    bearer,
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    before = rows(database, "tara_states")[0]
    message = f"Make valves unit price €30 each; {label} €{total}"
    ai.results.append(patch("Make valves unit price €30 each", "30"))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    if accepted:
        expected = deepcopy(before["notes"])
        expected["line_items"][0]["unit_price"] = "30"
        assert notes(database) == expected
        assert "Updated that." in reply_body(database, identifier)
    else:
        assert_rejected(database, identifier, before)


@pytest.mark.parametrize(
    "message",
    [
        "3 valves at €25 each invoice total €75",
        "3 valves unit price €25 grand total €75",
    ],
)
def test_stated_units_and_following_invoice_totals_remain_supported(
    message,
    messaging_client,
    database,
    seed,
    bearer,
):
    worker, ai = establish(messaging_client, database, seed, bearer, items=False)
    before = rows(database, "tara_states")[0]
    ai.results.append(
        proposal(
            [], line_items=[ITEMS[0]], line_items_evidence=message, intent="invoice_preparation"
        )
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert notes(database) == {**before["notes"], "line_items": [ITEMS[0]]}
    assert rows(database, "tara_states")[0]["version"] == before["version"] + 1
    assert "information is saved for preparation" in reply_body(database, identifier)
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["action"] == "notes_merged"
    assert run["error_code"] is None


@pytest.mark.parametrize("message", VAT_CHOICES)
@pytest.mark.parametrize("cropped", [False, True])
def test_formatted_vat_options_cannot_update_saved_rate(
    message,
    cropped,
    messaging_client,
    database,
    seed,
    bearer,
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    set_vat(worker, ai, messaging_client)
    before = rows(database, "tara_states")[0]
    ai.results.append(proposal([change("vat_rate", "23", "23%" if cropped else message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)
    assert notes(database)["vat_basis"] == "exclusive"
    assert notes(database)["vat_rate"] == "13.5"


@pytest.mark.parametrize(
    "message",
    [
        "VAT 23%\nVAT exempt",
        "VAT 23%; No VAT",
        "VAT 0%\nNo VAT",
        "VAT options:\nVAT exempt\nZero-rated",
        "VAT 23%\nincluding VAT\nexcluding VAT",
    ],
)
def test_formatted_options_also_protect_basis(
    message,
    messaging_client,
    database,
    seed,
    bearer,
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    set_vat(worker, ai, messaging_client)
    before = rows(database, "tara_states")[0]
    field_value = "exclusive" if "excluding" in message else "no_vat"
    ai.results.append(proposal([change("vat_basis", field_value, message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)


@pytest.mark.parametrize(
    "message,changes",
    [
        ("Use VAT 23%\nexcluding VAT", [("vat_rate", "23"), ("vat_basis", "exclusive")]),
        ("Use VAT 0%; including VAT", [("vat_rate", "0"), ("vat_basis", "inclusive")]),
        ("Use VAT 23%. The old job was exempt.", [("vat_rate", "23")]),
        ("VAT exempt.", [("vat_basis", "no_vat")]),
    ],
)
def test_compatible_vat_assertions_keep_other_notes(
    message,
    changes,
    messaging_client,
    database,
    seed,
    bearer,
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    set_vat(worker, ai, messaging_client)
    before = rows(database, "tara_states")[0]
    ai.results.append(proposal([change(field, value, message) for field, value in changes]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert notes(database) == {**before["notes"], **dict(changes)}
    assert "Updated that." in reply_body(database, identifier)
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["action"] == "notes_merged"
    assert run["error_code"] is None


@pytest.mark.parametrize("finding", ["total", "vat"])
def test_scope_rejection_preserves_the_other_tenant(
    finding,
    messaging_client,
    database,
    seed,
    bearer,
):
    worker, ai = establish(messaging_client, database, seed, bearer)
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
    before = next(
        row for row in rows(database, "tara_states") if row["tenant_id"] == seed.businesses["a"]
    )
    if finding == "total":
        message = "Change valves so the overall invoice total is €90."
        ai.results.append(patch(message, "30"))
    else:
        message = "VAT options:\nVAT exempt\nVAT 23%"
        ai.results.append(proposal([change("vat_rate", "23", message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    current = rows(database, "tara_states")
    assert (
        next(row for row in current if row["tenant_id"] == seed.businesses["a"])["notes"]
        == before["notes"]
    )
    assert next(row for row in current if row["tenant_id"] == seed.businesses["b"]) == other
    assert (
        next(row for row in current if row["tenant_id"] == seed.businesses["a"])["version"]
        == before["version"]
    )
    assert reply_body(database, identifier) == INVALID
    assert len(rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})) == 1
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["action"] is None
    assert run["error_code"] == "invalid_model_response"
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


@pytest.mark.parametrize(
    "message,field,value,evidence",
    [
        ("VAT 23%\nVAT options:\nincluding VAT", "vat_basis", "inclusive", "including VAT"),
        (
            "VAT 23%; Choose VAT treatment:\nincluding VAT",
            "vat_basis",
            "inclusive",
            "including VAT",
        ),
        (
            "VAT 23%\nWhich VAT treatment applies?\nincluding VAT",
            "vat_basis",
            "inclusive",
            "including VAT",
        ),
        ("VAT 23%\nChoices for VAT:\nincluding VAT", "vat_basis", "inclusive", "including VAT"),
        ("Use VAT 23%; Either:\nincluding VAT", "vat_basis", "inclusive", "including VAT"),
        ("Including VAT\nVAT options:\nVAT 23%", "vat_rate", "23", "23%"),
    ],
)
@pytest.mark.parametrize("cropped", [False, True])
def test_later_vat_choice_heading_preserves_saved_fields_and_clarifies(
    message,
    field,
    value,
    evidence,
    cropped,
    messaging_client,
    database,
    seed,
    bearer,
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    set_vat(worker, ai, messaging_client)
    before = rows(database, "tara_states")[0]
    ai.results.append(proposal([change(field, value, evidence if cropped else message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(database, identifier, before)
    assert notes(database)["vat_basis"] == "exclusive"
    assert notes(database)["vat_rate"] == "13.5"


def test_later_unrelated_question_preserves_affirmative_vat_updates(
    messaging_client, database, seed, bearer
):
    worker, ai = establish(messaging_client, database, seed, bearer)
    set_vat(worker, ai, messaging_client)
    before = rows(database, "tara_states")[0]
    message = "Use VAT 23%; which repairs apply?\nincluding VAT"
    ai.results.append(
        proposal([change("vat_rate", "23", message), change("vat_basis", "inclusive", message)])
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert notes(database) == {**before["notes"], "vat_rate": "23", "vat_basis": "inclusive"}
    assert "Updated that." in reply_body(database, identifier)
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["action"] == "notes_merged"
    assert run["error_code"] is None
