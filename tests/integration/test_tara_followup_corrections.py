"""Additional review cases preserve notes and use a persisted safe clarification."""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_messaging import rows, verify_link
from test_tara import accept, make_worker, notes
from test_tara import messaging_client as _messaging_client
from test_tara_review_corrections import change, complete_notes, proposal, reply_body

from anoifig.messaging.service import lookup_job
from anoifig.tara.service import FALLBACK, INVALID, Command

messaging_client = _messaging_client
pytestmark = pytest.mark.integration


def assert_rejected_correction(database, identifier, previous_state):
    state = rows(database, "tara_states")[0]
    assert state["notes"] == previous_state["notes"]
    assert state["version"] == previous_state["version"]
    assert state["pending_clarification"] == previous_state["pending_clarification"]
    assert reply_body(database, identifier) == INVALID
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["status"] == "complete"
    assert run["error_code"] == "invalid_model_response"
    assert run["action"] is None


@pytest.mark.parametrize(
    "message",
    [
        "Charge 625 in USD.",
        "Charge 625 (USD).",
        "USD amount 625.",
        "Charge 625 in $.",
    ],
)
@pytest.mark.parametrize("cropped_evidence", [False, True], ids=["complete", "cropped"])
def test_currency_qualifiers_cannot_change_saved_eur_amount(
    message, cropped_evidence, messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    complete_notes(worker, ai, messaging_client)
    previous_state = rows(database, "tara_states")[0]
    assert notes(database)["amount"] == "500"
    evidence = "625" if cropped_evidence else message
    ai.results.append(proposal([change("amount", "625", evidence)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected_correction(database, identifier, previous_state)
    assert len(rows(database, "outbox")) == 2


@pytest.mark.parametrize(
    ("message", "field", "value", "excerpt"),
    [
        ("VAT 23% is incorrect.", "vat_rate", "23", "23%"),
        ("VAT 23% is wrong.", "vat_rate", "23", "23%"),
        ("VAT included is wrong.", "vat_basis", "inclusive", "VAT included"),
        ("Is VAT 23% correct?", "vat_rate", "23", "23%"),
        ("Is this including VAT?", "vat_basis", "inclusive", "including VAT"),
        ("VAT 23% doesn't apply.", "vat_rate", "23", "23%"),
        ("VAT 23% shouldn't be used.", "vat_rate", "23", "23%"),
        ("VAT 23% cannot apply.", "vat_rate", "23", "23%"),
    ],
)
@pytest.mark.parametrize("cropped_evidence", [False, True], ids=["complete", "cropped"])
def test_vat_rejections_and_questions_cannot_be_saved_as_assertions(
    message, field, value, excerpt, cropped_evidence, messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    complete_notes(worker, ai, messaging_client)
    valid = "Use VAT rate 13.5%, excluding VAT."
    ai.results.append(
        proposal([change("vat_basis", "exclusive", valid), change("vat_rate", "13.5", valid)])
    )
    assert worker.process_delivery(accept(messaging_client, valid))
    previous_state = rows(database, "tara_states")[0]
    assert notes(database)["vat_basis"] == "exclusive"
    assert notes(database)["vat_rate"] == "13.5"
    evidence = excerpt if cropped_evidence else message
    ai.results.append(proposal([change(field, value, evidence)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected_correction(database, identifier, previous_state)
    assert len(rows(database, "outbox")) == 3


@pytest.mark.parametrize(
    ("message", "field", "value", "excerpt"),
    [
        ("VAT 23%, is that correct?", "vat_rate", "23", "23%"),
        ("VAT included, is that correct?", "vat_basis", "inclusive", "VAT included"),
        ("VAT 23%, incorrect.", "vat_rate", "23", "23%"),
        ("The amount €625 is incorrect.", "amount", "625", "€625"),
        ("Charge €625, is that correct?", "amount", "625", "€625"),
        ("Charge €625, incorrect.", "amount", "625", "€625"),
    ],
)
@pytest.mark.parametrize("cropped_evidence", [False, True], ids=["complete", "cropped"])
def test_soft_assessment_boundaries_preserve_existing_notes(
    message, field, value, excerpt, cropped_evidence, messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    complete_notes(worker, ai, messaging_client)
    valid = "Use VAT rate 13.5%, excluding VAT."
    ai.results.append(
        proposal([change("vat_basis", "exclusive", valid), change("vat_rate", "13.5", valid)])
    )
    assert worker.process_delivery(accept(messaging_client, valid))
    previous_state = rows(database, "tara_states")[0]
    evidence = excerpt if cropped_evidence else message
    ai.results.append(proposal([change(field, value, evidence)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected_correction(database, identifier, previous_state)
    assert len(rows(database, "outbox")) == 3


def test_stale_completion_preserves_newer_clarification_and_activity(
    messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    identifier = accept(messaging_client, "Actually €625.")
    with Session(worker.engine) as session, session.begin():
        job = lookup_job(session, identifier)
    command = worker.tara._prepare(job)
    assert isinstance(command, Command)
    newer_notes = {
        "customer_name": "Una",
        "work_description": "repairs",
        "amount": "700",
        "vat_basis": "exclusive",
    }
    with database.admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE tara_states SET notes = CAST(:notes AS jsonb), version = version + 1, "
                "pending_clarification = 'vat_rate', updated_at = now()"
            ),
            {"notes": json.dumps(newer_notes)},
        )
    newer_state = rows(database, "tara_states")[0]
    reservation = rows(database, "tara_usage")[0]
    result = proposal([change("amount", "625", "€625")])
    assert worker.tara._complete(command, result, None)
    assert rows(database, "tara_states")[0] == newer_state
    assert rows(database, "tara_usage")[0] == reservation
    assert reply_body(database, identifier) == FALLBACK
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["error_code"] == "stale_state"
    assert run["action"] is None
    assert worker.process_delivery(identifier)
    assert ai.requests == []
    assert len(rows(database, "outbox")) == 1
