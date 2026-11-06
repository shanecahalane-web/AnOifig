"""Harness controls retain the real SDK resolver and the total parent deadline."""

import signal
import time

import pytest
from test_tara_provider_isolation import REQUEST, events, launch
from test_tara_provider_isolation import prepared_child_cleanup as prepared_child_cleanup
from test_tara_provider_isolation import settings as settings

from anoifig.tara.provider import OpenAIProvider, ProviderFailure


@pytest.mark.parametrize("proxy", ["http://127.0.0.1:1", "http://platform-proxy.invalid:8080"])
def test_dns_fault_is_independent_of_host_proxy(settings, monkeypatch, tmp_path, proxy):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(name, proxy)
    journal, children = launch(monkeypatch, tmp_path, "dns")
    started = time.monotonic()
    with pytest.raises(ProviderFailure):
        OpenAIProvider(settings).respond(REQUEST)
    elapsed = time.monotonic() - started
    assert 1.5 <= elapsed < 3.5
    assert len(children) == 1 and children[0].poll() is not None
    recorded = events(journal)
    assert [event["host"] for event in recorded if event["event"] == "dns_started"] == [
        "tara-provider.invalid"
    ]
    assert not any(event["event"] == "dns_finished" for event in recorded)


@pytest.mark.parametrize("scenario", ["startup", "startup_ignore_term"])
def test_total_deadline_contains_child_setup(settings, monkeypatch, tmp_path, scenario):
    journal, children = launch(monkeypatch, tmp_path, scenario)
    started = time.monotonic()
    with pytest.raises(ProviderFailure):
        OpenAIProvider(settings).respond(REQUEST)
    elapsed = time.monotonic() - started
    assert 1.5 <= elapsed < 3.5
    assert len(children) == 1 and children[0].poll() is not None
    recorded = events(journal)
    assert [event["event"] for event in recorded] == ["started", "setup_started"]
    if scenario == "startup_ignore_term":
        assert children[0].returncode == -signal.SIGKILL
    time.sleep(0.05)
    assert events(journal) == recorded


def test_fixture_preparation_makes_no_provider_request(settings, monkeypatch, tmp_path):
    journal, children = launch(monkeypatch, tmp_path, "success")
    assert [event["event"] for event in events(journal)] == ["started", "prepared"]
    assert len(children) == 1 and children[0].poll() is None
    result = OpenAIProvider(settings).respond(REQUEST)
    assert result.decision.reply.text == "Hello"
    assert [event["event"] for event in events(journal)] == ["started", "prepared", "sdk_request"]
    assert children[0].returncode == 0


def test_full_transport_also_succeeds_without_fixture_preparation(settings, monkeypatch, tmp_path):
    # A cold positive control has a realistic setup allowance. The two-second
    # startup-stall tests above continue to prove the total deadline boundary.
    settings = settings.model_copy(update={"tara_deadline_seconds": 20})
    journal, children = launch(monkeypatch, tmp_path, "cold_success")
    assert children == []
    result = OpenAIProvider(settings).respond(REQUEST)
    assert result.decision.reply.text == "Hello"
    assert [event["event"] for event in events(journal)] == ["started", "sdk_request"]
    assert len(children) == 1 and children[0].returncode == 0
    payload = next(event["body"] for event in events(journal) if event["event"] == "sdk_request")
    assert payload["store"] is False and payload["parallel_tool_calls"] is False
    assert payload["tools"][0]["function"]["strict"] is True
