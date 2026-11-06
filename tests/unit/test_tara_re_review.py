"""The independent reviewer messages also exercise the pure final boundary."""

import json
from pathlib import Path

import pytest
from test_tara_review_authority import saved

from anoifig.tara.schemas import ProposedNotes, apply_proposal

CASES = json.loads(
    (Path(__file__).parents[1] / "scenarios/tara_authority_re_review.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["label"])
def test_re_review(case):
    notes = saved(items=case["mode"] != "scalar", vat=case["mode"] == "vat")
    before = notes.model_dump()
    proposal = ProposedNotes(
        intent="correction",
        changes=case["changes"],
        line_items=None,
        line_items_evidence=None,
        line_item_patches=case["patches"],
    )
    if case["positive"]:
        updated = apply_proposal(
            notes, proposal, case["message"], expected_version=7, current_version=7
        )
        for change in case["changes"]:
            assert getattr(updated, change["field"]) == change["value"]
        for patch in case["patches"]:
            for change in patch["changes"]:
                assert (
                    getattr(updated.line_items[patch["index"]], change["field"]) == change["value"]
                )
    else:
        with pytest.raises(ValueError):
            apply_proposal(notes, proposal, case["message"], expected_version=7, current_version=7)
    assert notes.model_dump() == before
