"""Exercise the real supported SDK over an in-memory HTTP transport, never an API."""

import json

import httpx
import pytest
from openai import OpenAI
from pydantic import ValidationError

from anoifig.config import Settings
from anoifig.tara.provider import AIRequest, OpenAIProvider, ProviderFailure
from anoifig.tara.schemas import (
    InvoiceNotes,
    ProposedNotes,
    apply_proposal,
    money,
    numeric_evidence,
)


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://unit:unit@localhost/anoifig_unit",
        tara_mode="openai",
        openai_api_key="synthetic-key-never-sent",
        tara_input_price_usd="1",
        tara_output_price_usd="4",
        tara_model="configured-model",
    )


def completion(message=None, **overrides):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "configured-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": message
                or {
                    "role": "assistant",
                    "content": json.dumps({"intent": "general", "text": "How can I help?"}),
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        **overrides,
    }


def provider(settings, handler):
    client = OpenAI(
        api_key="synthetic-key-never-sent",
        max_retries=settings.tara_max_retries,
        timeout=settings.tara_timeout_seconds,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return OpenAIProvider(settings, client=client)


REQUEST = AIRequest({}, (), "Hello Tara")


def test_sdk_structured_response_and_secure_request(settings):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion())

    result = provider(settings, handler).respond(REQUEST)
    assert result.decision.reply.text == "How can I help?"
    assert result.input_tokens == 100 and result.output_tokens == 20
    payload = requests[0]
    assert payload["model"] == "configured-model"
    assert payload["max_completion_tokens"] == settings.tara_max_output_tokens
    assert payload["store"] is False and payload["parallel_tool_calls"] is False
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert len(payload["tools"]) == 1
    assert payload["tools"][0]["function"]["name"] == "propose_invoice_notes"
    assert "tenant_id" not in json.dumps(payload)


def tool_message(name="propose_invoice_notes", **argument_overrides):
    args = {
        "intent": "correction",
        "changes": [{"field": "amount", "value": "500", "evidence": "500"}],
        "line_items": None,
        "line_items_evidence": None,
        **argument_overrides,
    }
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-test",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def test_sdk_tool_call_is_proposal_only(settings):
    result = provider(
        settings, lambda _: httpx.Response(200, json=completion(tool_message()))
    ).respond(REQUEST)
    assert result.decision.proposal.changes[0].value == "500"
    assert result.decision.reply is None


@pytest.mark.parametrize(
    "case", ["unknown", "tenant", "many", "refusal", "json", "missing_usage", "truncated"]
)
def test_sdk_rejects_untrusted_outputs(settings, case):
    message = tool_message()
    data = completion(message)
    if case == "unknown":
        message["tool_calls"][0]["function"]["name"] = "issue_invoice"
    elif case == "tenant":
        data = completion(tool_message(tenant_id="other-tenant"))
    elif case == "many":
        message["tool_calls"] *= 2
    elif case == "refusal":
        message["refusal"] = "Cannot process"
    elif case == "json":
        message["tool_calls"][0]["function"]["arguments"] = "not JSON"
    elif case == "missing_usage":
        data["usage"] = None
    else:
        data["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ProviderFailure):
        provider(settings, lambda _: httpx.Response(200, json=data)).respond(REQUEST)


@pytest.mark.parametrize("mode", ["timeout", "server_error", "rate_limit"])
def test_bounded_sdk_retries_and_generic_failures(settings, monkeypatch, mode):
    calls = []
    monkeypatch.setattr("openai._base_client.time.sleep", lambda _: None)

    def handler(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("sensitive details", request=request)
        return httpx.Response(
            429 if mode == "rate_limit" else 503,
            json={"error": {"message": "sensitive details", "type": "api_error"}},
        )

    with pytest.raises(ProviderFailure) as captured:
        provider(settings, handler).respond(REQUEST)
    assert len(calls) == settings.tara_max_retries + 1
    assert str(captured.value) == ""


@pytest.mark.parametrize(
    "value", ["NaN", "Infinity", "-1", "1e3", "1.005", "1,000", "1000001", "01", " 5"]
)
def test_money_is_deterministic_and_bounded(value):
    with pytest.raises(ValueError):
        money(value)
    with pytest.raises(ValidationError):
        InvoiceNotes(amount=value)


@pytest.mark.parametrize("evidence", ["1500", "-500", "5e2", "500.001", "0.500"])
def test_numeric_evidence_does_not_accept_substrings_or_round(evidence):
    assert not numeric_evidence("500", evidence)


def test_non_euro_currency_and_invented_fields_are_not_supported():
    with pytest.raises(ValidationError):
        InvoiceNotes(currency="GBP")
    with pytest.raises(ValueError):
        apply_proposal(
            InvoiceNotes(),
            ProposedNotes.model_validate(
                {
                    "intent": "invoice_preparation",
                    "changes": [{"field": "customer_name", "value": "Mary", "evidence": "John"}],
                    "line_items": None,
                    "line_items_evidence": None,
                }
            ),
            "Invoice John",
        )


@pytest.mark.parametrize(
    "config",
    [
        {"openai_api_key": None},
        {"openai_api_key": ""},
        {"tara_input_price_usd": "0"},
        {"tara_output_price_usd": "NaN"},
        {"tara_max_retries": 10},
        {"tara_memory_days": 1000},
    ],
)
def test_live_configuration_requires_secrets_prices_and_bounds(settings, config):
    values = settings.model_dump()
    values.update(config)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_key_never_appears_in_configuration_representation(settings):
    assert "synthetic-key-never-sent" not in repr(settings)
    assert "synthetic-key-never-sent" not in settings.model_dump_json()


@pytest.mark.parametrize(
    ("value", "evidence"),
    [
        ("500", "500e, cheers"),
        ("1500", "1.5k for the job"),
        ("3", "3x25 for valves"),
        ("25", "3x25 for valves"),
        ("450", "450EUR"),
        ("500", "€500, thanks"),
    ],
)
def test_irish_trade_amount_shorthand(value, evidence):
    assert numeric_evidence(value, evidence)


@pytest.mark.parametrize("evidence", ["£500", "$500", "500 GBP", "500 USD"])
def test_other_currency_is_not_silently_interpreted_as_eur(evidence):
    assert not numeric_evidence("500", evidence)


@pytest.mark.parametrize(
    ("value", "evidence"),
    [
        ("inclusive", "Not including VAT"),
        ("no_vat", "Invoice John 500"),
        ("exclusive", "I don't know about VAT"),
    ],
)
def test_vat_basis_cannot_be_invented(value, evidence):
    from anoifig.tara.schemas import vat_evidence

    assert not vat_evidence(value, evidence)


def test_empty_line_replacement_cannot_silently_delete_collected_items():
    with pytest.raises(ValidationError):
        ProposedNotes(intent="correction", changes=[], line_items=[], line_items_evidence="Hello")


@pytest.mark.parametrize("field", ["customer_name", "work_description", "customer_details"])
def test_blank_customer_details_are_not_accepted(field):
    with pytest.raises(ValidationError):
        InvoiceNotes(**{field: "   "})
