"""Independent re-review cases through signed ingress and restricted PostgreSQL."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import test_tara
from sqlalchemy import text
from test_messaging import rows
from test_tara import accept
from test_tara import messaging_client as messaging_client
from test_tara_authority_persistence import (
    assert_accepted,
    assert_rejected,
    establish_complete,
    saved_state,
)
from test_tara_review_corrections import proposal

pytestmark = pytest.mark.integration
CASES = json.loads(
    (Path(__file__).parents[1] / "scenarios/tara_authority_re_review.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["label"])
def test_re_review(case, messaging_client, database, seed, bearer):
    worker, ai = establish_complete(
        messaging_client,
        database,
        seed,
        bearer,
        scalar=case["mode"] == "scalar",
        vat=case["mode"] == "vat",
    )
    before = saved_state(database)
    ai.results.append(proposal(case["changes"], line_item_patches=case["patches"]))
    identifier = accept(messaging_client, case["message"])
    assert worker.process_delivery(identifier)
    if not case["positive"]:
        assert_rejected(worker, ai, database, identifier, before)
        return
    expected = deepcopy(before["notes"])
    for change in case["changes"]:
        expected[change["field"]] = change["value"]
    for patch in case["patches"]:
        for change in patch["changes"]:
            expected["line_items"][patch["index"]][change["field"]] = change["value"]
    assert_accepted(
        database,
        identifier,
        before,
        expected,
        contact=any(c["field"] == "customer_details" for c in case["changes"]),
    )
    after = saved_state(database)
    calls = len(ai.requests)
    assert worker.process_delivery(identifier)
    assert len(ai.requests) == calls
    assert saved_state(database) == after


def test_accept_selects_inbound_when_an_old_outbox_becomes_discoverable(
    messaging_client, database, seed, bearer, monkeypatch
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, scalar=True)
    before = saved_state(database)
    old = rows(database, "message_jobs", "WHERE kind = 'outbound'")[0]["id"]
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE message_jobs SET claim_until = now() + interval '1 hour' WHERE id = :id"),
            {"id": old},
        )
    discover = test_tara.rows_from_client

    def expire_after_discovery(client):
        result = discover(client)
        with database.admin.begin() as connection:
            connection.execute(
                text("UPDATE message_jobs SET claim_until = NULL WHERE id = :id"), {"id": old}
            )
        return result

    monkeypatch.setattr(test_tara, "rows_from_client", expire_after_discovery)
    message = "Set amount €700"
    ai.results.append(proposal([{"field": "amount", "value": "700", "evidence": message}]))
    identifier = accept(messaging_client, message)
    inbound = rows(database, "messages", "WHERE body = :body", {"body": message})[0]
    assert identifier == inbound["id"]
    assert worker.process_delivery(identifier)
    expected = deepcopy(before["notes"])
    expected["amount"] = "700"
    assert_accepted(database, identifier, before, expected)
