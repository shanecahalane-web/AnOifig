"""Independent re-review cases through signed ingress and restricted PostgreSQL."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
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
CASES = json.loads((Path(__file__).parents[1] / "scenarios/tara_final_review.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["label"])
def test_final_review(case, messaging_client, database, seed, bearer):
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
        # The shared helper has also replayed the delivery. Keep the version
        # unchanged after that duplicate, as well as after the initial rejection.
        assert saved_state(database)["version"] == before["version"]
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
