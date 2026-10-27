"""Harness controls retain the real SDK resolver and the total parent deadline."""

import signal
import time

import pytest
from test_tara_provider_isolation import REQUEST, events, launch
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
