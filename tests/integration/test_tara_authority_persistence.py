"""Six independent-review authority failures through signed ingress and runtime RLS.

The model transport is deliberately adversarial. Each rejection compares the whole
saved notes object, version, durable action and exact application-owned reply.
"""

from copy import deepcopy

import pytest
from sqlalchemy import text
from test_messaging import OTHER_PHONE, rows, set_context, verify_link
from test_tara import accept
from test_tara import messaging_client as _messaging_client
from test_tara_review_corrections import change, proposal
from test_tara_scope_persistence import ITEMS, establish, set_vat

from anoifig.tara.service import INVALID

messaging_client = _messaging_client
pytestmark = pytest.mark.integration


def item_patch(evidence, *, index=0, description="valves", field="unit_price", value="30"):
    return {
        "index": index,
        "description": description,
        "evidence": evidence,
        "changes": [{"field": field, "value": value, "evidence": evidence}],
    }


def saved_state(database):
    return deepcopy(dict(rows(database, "tara_states")[0]))


def establish_complete(client, database, seed, bearer, *, scalar=False, vat=False):
    worker, ai = establish(client, database, seed, bearer, items=not scalar)
    if scalar:
        message = "Set amount €600; labour €400; materials €200"
        ai.results.append(
            proposal(
                [
                    change("amount", "600", "Set amount €600"),
                    change("labour", "400", "labour €400"),
                    change("materials", "200", "materials €200"),
                ]
            )
        )
        assert worker.process_delivery(accept(client, message))
        assert saved_state(database)["notes"]["amount"] == "600"
    message = "Set customer details to 1 Oak Road"
    ai.results.append(proposal([change("customer_details", "1 Oak Road", message)]))
    assert worker.process_delivery(accept(client, message))
    assert saved_state(database)["notes"]["customer_details"] == "1 Oak Road"
    if vat:
        set_vat(worker, ai, client)
        assert saved_state(database)["notes"]["vat_rate"] == "13.5"
    return worker, ai


def assert_rejected(worker, ai, database, identifier, before):
    after = next(
        row
        for row in rows(database, "tara_states")
        if row["conversation_id"] == before["conversation_id"]
    )
    assert after["notes"] == before["notes"]
    assert after["version"] == before["version"]
    replies = rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})
    assert len(replies) == 1
    assert replies[0]["body"] == INVALID
    assert "Updated that." not in replies[0]["body"]
    assert "information is saved for preparation" not in replies[0]["body"]
    assert len(rows(database, "outbox", "WHERE message_id = :id", {"id": replies[0]["id"]})) == 1
    runs = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})
    assert len(runs) == 1
    assert runs[0]["status"] == "complete"
    assert runs[0]["action"] is None
    assert runs[0]["error_code"] == "invalid_model_response"
    requests = len(ai.requests)
    assert worker.process_delivery(identifier)
    assert len(ai.requests) == requests
    assert len(rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})) == 1
    assert (
        next(
            row["notes"]
            for row in rows(database, "tara_states")
            if row["conversation_id"] == before["conversation_id"]
        )
        == before["notes"]
    )


def assert_accepted(database, identifier, before, expected, *, contact=False):
    after = saved_state(database)
    assert after["notes"] == expected
    assert after["version"] == before["version"] + 1
    replies = rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})
    assert len(replies) == 1
    assert "Updated that." in replies[0]["body"]
    run = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})[0]
    assert run["action"] == ("contact_notes_merged" if contact else "notes_merged")
    assert run["error_code"] is None


@pytest.mark.parametrize(
    "message,value",
    [
        ("The address is 25 Main Street.", "25"),
        ("Invoice reference 500.", "500"),
        ("There are 3 valves.", "3"),
        ("The job took 8 hours.", "8"),
    ],
)
@pytest.mark.parametrize("field", ["amount", "labour", "materials"])
@pytest.mark.parametrize("cropped", [False, True])
def test_nonfinancial_numbers_do_not_authorise_any_scalar_charge(
    message, value, field, cropped, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, scalar=True)
    before = saved_state(database)
    ai.results.append(proposal([change(field, value, value if cropped else message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Labour took 8 hours", "labour", "8"),
        ("Set materials quantity to 3", "materials", "3"),
        ("Invoice reference €500", "amount", "500"),
        ("Total quantity 3", "amount", "3"),
    ],
)
def test_nonfinancial_roles_remain_nonfinancial_despite_charge_words(
    message, field, value, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, scalar=True)
    before = saved_state(database)
    ai.results.append(proposal([change(field, value, value)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize(
    "message,value,field",
    [
        ("Invoice John €500 for repairs", "500", "labour"),
        ("Invoice John €500 for repairs", "500", "materials"),
        ("€100 for labour", "100", "amount"),
        ("€100 for labour", "100", "materials"),
        ("Materials €200", "200", "amount"),
        ("Materials €200", "200", "labour"),
    ],
)
def test_a_financial_value_cannot_be_borrowed_for_a_different_scalar_field(
    message, value, field, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, scalar=True)
    before = saved_state(database)
    ai.results.append(proposal([change(field, value, message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


COLLECTIVE_TARGETS = [
    "total for everything",
    "combined total",
    "total across the two items",
    "total for the lot",
    "total for these items",
    "total of the complete order",
]


@pytest.mark.parametrize("label", COLLECTIVE_TARGETS)
@pytest.mark.parametrize("quantity_patch", [False, True])
def test_collective_total_cannot_establish_one_selected_item(
    label, quantity_patch, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    if quantity_patch:
        message = f"Change valves quantity to 4 so the {label} is €100."
        patch = item_patch(message, field="quantity", value="4")
    else:
        message = f"Change valves so the {label} is €90."
        patch = item_patch(message)
    ai.results.append(proposal([], line_item_patches=[patch]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize("replacement", [False, True])
@pytest.mark.parametrize("label", ["total for everything", "total of the complete order"])
def test_collective_total_cannot_ground_initial_or_replacement_lists(
    replacement, label, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(
        messaging_client, database, seed, bearer, scalar=not replacement
    )
    before = saved_state(database)
    prefix = "Replace all line items with: " if replacement else ""
    message = f"{prefix}3 valves for a {label} of €90 and 2 elbows at €10."
    ai.results.append(
        proposal(
            [],
            line_items=[{**ITEMS[0], "unit_price": "30"}, ITEMS[1]],
            line_items_evidence=message,
        )
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


FORMATTED_VAT_HEADINGS = [
    ("Which VAT treatment applies?", "-"),
    ("*Which VAT treatment applies?*", "-"),
    ("**Which VAT treatment applies?**", "1."),
    ("### Which VAT treatment applies?", "(a)"),
    ("> Which VAT treatment applies?", "> -"),
    ("*VAT options:*", "-"),
]


@pytest.mark.parametrize("heading,marker", FORMATTED_VAT_HEADINGS)
@pytest.mark.parametrize(
    "field,value,answer",
    [("vat_rate", "23", "VAT 23%"), ("vat_basis", "inclusive", "including VAT")],
)
@pytest.mark.parametrize("cropped", [False, True])
def test_formatted_vat_questions_and_options_do_not_become_instructions(
    heading, marker, field, value, answer, cropped, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, vat=True)
    before = saved_state(database)
    message = f"{heading}\n\n  {marker} {answer}"
    ai.results.append(proposal([change(field, value, answer if cropped else message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize(
    "current",
    ["now use", "this one is", "instead use", "this invoice is", "the new invoice is"],
)
@pytest.mark.parametrize("field", ["vat_rate", "vat_basis"])
def test_historical_reference_cannot_hide_later_current_contradiction(
    current, field, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, vat=True)
    before = saved_state(database)
    if field == "vat_rate":
        message = f"Use VAT 23%; the old invoice is exempt, but {current} VAT 0%."
        value, evidence = "23", "23%"
    else:
        message = f"Use including VAT; the old invoice is VAT exempt, but {current} excluding VAT."
        value, evidence = "inclusive", "including VAT"
    ai.results.append(proposal([change(field, value, evidence)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize(
    "suffix",
    [
        "; do not make this change.",
        "; actually cancel that.",
        ", or leave the invoice as is.",
        "; except keep valves unchanged.",
        "; only if John agrees.",
    ],
)
def test_later_cancellation_or_preservation_vetoes_the_proposed_price(
    suffix, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    evidence = "Change valves unit price €30"
    ai.results.append(proposal([], line_item_patches=[item_patch(evidence)]))
    identifier = accept(messaging_client, evidence + suffix)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


def test_cancelled_scalar_amount_preserves_all_other_saved_financial_fields(
    messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, scalar=True)
    before = saved_state(database)
    message = "Set amount €500; no, cancel that."
    ai.results.append(proposal([change("amount", "500", "€500")]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


UNAUTHORISED_TEXT = [
    ("Do not change customer name to Jack.", "customer_name", "Jack"),
    ("Do not change work description to maintenance.", "work_description", "maintenance"),
    (
        "The previous invoice was for Jack; this invoice is for John.",
        "customer_name",
        "Jack",
    ),
    ("Do not replace the address with 25 Main Street.", "customer_details", "25 Main Street"),
    ("Customer name Jack; customer name Una.", "customer_name", "Jack"),
    (
        "Work description: repairs; work description: maintenance.",
        "work_description",
        "maintenance",
    ),
    ("Address: 1 Oak Road; address: 25 Main Street.", "customer_details", "25 Main Street"),
    ("Work description: Jack; customer name: John.", "customer_name", "Jack"),
    ("Customer name: Jack; work description: maintenance.", "work_description", "Jack"),
]


@pytest.mark.parametrize("message,field,value", UNAUTHORISED_TEXT)
@pytest.mark.parametrize("cropped", [False, True])
def test_text_mutations_require_affirmative_current_field_authority(
    message, field, value, cropped, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    ai.results.append(proposal([change(field, value, value if cropped else message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize("finding", ["vat-question", "scalar-number", "negated-text", "cancel"])
def test_one_unsupported_change_rejects_the_entire_mixed_proposal(
    finding, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, vat=True)
    before = saved_state(database)
    valid = "Change valves unit price €30 each"
    patches = [item_patch(valid)]
    changes = []
    if finding == "vat-question":
        message = valid + "; *Which VAT treatment applies?*\n- VAT 23%"
        changes = [change("vat_rate", "23", "VAT 23%")]
    elif finding == "scalar-number":
        message = "Set customer name Jack; the address is 25 Main Street"
        changes = [change("customer_name", "Jack", "Jack"), change("labour", "25", "25")]
        patches = []
    elif finding == "negated-text":
        message = valid + "; do not change work description to maintenance"
        changes = [change("work_description", "maintenance", "maintenance")]
    else:
        other = "Change elbows unit price €12 each"
        message = valid + "; " + other + "; do not make this change"
        patches.append(item_patch(other, index=1, description="elbows", value="12"))
    ai.results.append(proposal(changes, line_item_patches=patches))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)


@pytest.mark.parametrize(
    "message",
    [
        "Change valves unit price €30 each; keep elbows unchanged.",
        "Change valves line total €90; leave elbows at €10.",
        "Change valves overall price €90.",
    ],
)
def test_explicit_item_prices_and_other_item_preservation_remain_supported(
    message, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    evidence = message.split(";")[0].rstrip(".")
    ai.results.append(proposal([], line_item_patches=[item_patch(evidence)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    expected = deepcopy(before["notes"])
    expected["line_items"][0]["unit_price"] = "30"
    assert_accepted(database, identifier, before, expected)


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("500e, cheers", "amount", "500"),
        ("1.5k for the job", "amount", "1500"),
        ("Make it €500", "amount", "500"),
        ("Invoice John €500 for 3 hours work", "amount", "500"),
        ("Labour 500", "labour", "500"),
        ("€100 for labour", "labour", "100"),
    ],
)
def test_unambiguous_financial_shorthand_remains_supported(
    message, field, value, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, scalar=True)
    before = saved_state(database)
    ai.results.append(proposal([change(field, value, message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_accepted(database, identifier, before, {**before["notes"], field: value})


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Set customer name Jack", "customer_name", "Jack"),
        ("Set work description maintenance", "work_description", "maintenance"),
        ("Set customer details 25 Main Street", "customer_details", "25 Main Street"),
        (
            "The previous invoice was for Jack; this invoice is for John.",
            "customer_name",
            "John",
        ),
    ],
)
def test_current_affirmative_text_updates_keep_financial_state(
    message, field, value, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    ai.results.append(proposal([change(field, value, value)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_accepted(
        database,
        identifier,
        before,
        {**before["notes"], field: value},
        contact=field == "customer_details",
    )


@pytest.mark.parametrize(
    "message",
    [
        "**Use VAT 23%**; including VAT",
        "The old invoice is VAT exempt, but now use VAT 23%; including VAT",
    ],
)
def test_affirmative_formatted_or_current_vat_instructions_remain_supported(
    message, messaging_client, database, seed, bearer
):
    worker, ai = establish_complete(messaging_client, database, seed, bearer, vat=True)
    before = saved_state(database)
    ai.results.append(
        proposal(
            [change("vat_rate", "23", "23%"), change("vat_basis", "inclusive", "including VAT")]
        )
    )
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_accepted(
        database,
        identifier,
        before,
        {**before["notes"], "vat_basis": "inclusive", "vat_rate": "23"},
    )


def test_rejection_preserves_other_tenant_and_runtime_rls(messaging_client, database, seed, bearer):
    worker, ai = establish_complete(messaging_client, database, seed, bearer)
    before = saved_state(database)
    verify_link(messaging_client, seed, bearer, phone=OTHER_PHONE, tenant="b", subject="owner-b")
    message = "Invoice Una for repairs; amount €700; no VAT"
    ai.results.append(
        proposal(
            [
                change("customer_name", "Una", "Una"),
                change("work_description", "repairs", "repairs"),
                change("amount", "700", "amount €700"),
                change("vat_basis", "no_vat", "no VAT"),
            ],
            intent="invoice_preparation",
        )
    )
    assert worker.process_delivery(accept(messaging_client, message, phone=OTHER_PHONE))
    other = deepcopy(
        dict(
            next(
                row
                for row in rows(database, "tara_states")
                if row["tenant_id"] == seed.businesses["b"]
            )
        )
    )
    message = "Change valves so the total for everything is €90"
    ai.results.append(proposal([], line_item_patches=[item_patch(message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    assert_rejected(worker, ai, database, identifier, before)
    with database.runtime.begin() as connection:
        set_context(connection, seed, subject="owner-b", tenant="b")
        for table in ("tara_states", "tara_runs", "tara_usage"):
            assert (
                connection.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant"),
                    {"tenant": seed.businesses["a"]},
                )
                == 0
            )
            assert (
                connection.execute(
                    text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :tenant"),
                    {"tenant": seed.businesses["a"]},
                ).rowcount
                == 0
            )
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
