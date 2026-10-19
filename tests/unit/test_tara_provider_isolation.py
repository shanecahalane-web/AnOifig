"""Offline process/real resolver lifecycle tests for the public sync adapter."""

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from anoifig.config import Settings
from anoifig.tara import provider_isolation
from anoifig.tara.provider import AIRequest, OpenAIProvider, ProviderFailure

HELPER = Path(__file__).parents[1] / "helpers" / "tara_provider_child.py"
REQUEST = AIRequest({}, (), "Hello Tara", state_version=7, pending_clarification="vat_rate")


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://synthetic:private@localhost/anoifig_unit",
        tara_mode="openai",
        openai_api_key="synthetic-key-never-sent",
        tara_input_price_usd="1",
        tara_output_price_usd="4",
        tara_model="configured-model",
        tara_deadline_seconds=2,
    )


def events(journal):
    if not journal.exists():
        return []
    return [json.loads(line) for line in journal.read_text().splitlines()]


def launch(monkeypatch, tmp_path, scenario):
    journal = tmp_path / "provider-events.jsonl"
    children = []
    original = subprocess.Popen

    def start_child(output):
        child = original(
            [sys.executable, "-I", str(HELPER), scenario, str(journal), str(os.getpid())],
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.PIPE,
            env={
                name: value
                for name, value in os.environ.items()
                if name in provider_isolation._NETWORK_ENVIRONMENT
            },
            close_fds=True,
        )
        children.append(child)
        return child

    monkeypatch.setattr(provider_isolation, "_start_child", start_child)
    return journal, children


def test_isolated_sdk_result_and_complete_payload(settings, monkeypatch, tmp_path):
    settings = settings.model_copy(update={"tara_deadline_seconds": 4})
    journal, children = launch(monkeypatch, tmp_path, "success")
    result = OpenAIProvider(settings).respond(REQUEST)
    assert result.decision.reply.text == "Hello"
    assert (result.input_tokens, result.output_tokens) == (100, 20)
    assert len(children) == 1 and children[0].returncode == 0
    payload = next(event["body"] for event in events(journal) if event["event"] == "sdk_request")
    data = json.loads(payload["messages"][1]["content"])
    assert data["current_message"] == "Hello Tara" and data["state_version"] == 7
    assert data["pending_clarification"] == "vat_rate"
    assert payload["store"] is False and payload["parallel_tool_calls"] is False
    assert "tenant_id" not in json.dumps(payload)


@pytest.mark.parametrize("scenario", ["dns", "dns_ignore_term", "late", "retry"])
def test_deadline_bounds_real_resolver_retry_and_uncancellable_transport(
    settings, monkeypatch, tmp_path, scenario
):
    journal, children = launch(monkeypatch, tmp_path, scenario)
    started = time.monotonic()
    with pytest.raises(ProviderFailure) as error:
        OpenAIProvider(settings).respond(REQUEST)
    elapsed = time.monotonic() - started
    assert 1.5 <= elapsed < 3.5
    assert str(error.value) == ""
    assert len(children) == 1 and children[0].poll() is not None
    recorded = events(journal)
    event_names = [event["event"] for event in recorded]
    assert (
        "dns_started" in event_names if scenario.startswith("dns") else "sdk_request" in event_names
    )
    assert "dns_finished" not in event_names and "late_result" not in event_names
    if scenario == "dns_ignore_term":
        assert children[0].returncode == -signal.SIGKILL
    if scenario == "retry":
        assert event_names.count("sdk_request") == 1
    # A killed process cannot later return or make another retry after fallback.
    time.sleep(0.05)
    assert events(journal) == recorded


def test_keyboard_interrupt_kills_request_child(settings, monkeypatch, tmp_path):
    settings = settings.model_copy(update={"tara_deadline_seconds": 4})
    journal, children = launch(monkeypatch, tmp_path, "dns")
    original_start = provider_isolation._start_child

    def interrupted_start(output):
        child = original_start(output)
        original_communicate = child.communicate

        def communicate(payload, timeout):
            # Feed the real SDK request and let the real resolver start, then
            # interrupt the synchronous parent while it owns the live child.
            with pytest.raises(subprocess.TimeoutExpired):
                original_communicate(payload, timeout=2.5)
            assert "dns_started" in [event["event"] for event in events(journal)]
            raise KeyboardInterrupt

        child.communicate = communicate
        return child

    monkeypatch.setattr(provider_isolation, "_start_child", interrupted_start)
    with pytest.raises(KeyboardInterrupt):
        OpenAIProvider(settings).respond(REQUEST)
    assert len(children) == 1 and children[0].poll() is not None
    assert "dns_finished" not in [event["event"] for event in events(journal)]


def test_sigkill_worker_also_kills_its_live_resolver_child(tmp_path):
    journal = tmp_path / "parent-death.jsonl"
    harness = HELPER.with_name("tara_provider_parent.py")
    parent = subprocess.Popen(
        [sys.executable, "-I", str(harness), str(journal)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    child_pid = None
    try:
        ready_by = time.monotonic() + 5
        while time.monotonic() < ready_by:
            started = next(
                (event for event in events(journal) if event["event"] == "dns_started"), None
            )
            if started is not None:
                child_pid = started["pid"]
                break
            if parent.poll() is not None:
                pytest.fail(f"Worker harness exited before DNS: {parent.communicate()[1]!r}")
            time.sleep(0.02)
        assert child_pid is not None, "Real HTTPX resolver must start before killing its parent"
        parent.kill()
        parent.wait(timeout=2)
        dead_by = time.monotonic() + 2
        while time.monotonic() < dead_by:
            status = Path(f"/proc/{child_pid}/stat")
            if not status.exists() or status.read_text().split()[2] == "Z":
                break
            time.sleep(0.02)
        else:
            pytest.fail("Parent SIGKILL left the SDK resolver child executing")
        assert "dns_finished" not in [event["event"] for event in events(journal)]
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)
        if child_pid is not None:
            with suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)
        if parent.stderr is not None:
            parent.stderr.close()


@pytest.mark.parametrize("scenario", ["malformed", "oversized"])
def test_invalid_ipc_result_fails_closed(settings, monkeypatch, tmp_path, scenario):
    _, children = launch(monkeypatch, tmp_path, scenario)
    with pytest.raises(ProviderFailure) as error:
        OpenAIProvider(settings).respond(REQUEST)
    assert str(error.value) == "" and children[0].poll() is not None


def test_child_environment_only_preserves_proxy_and_certificate_trust(
    settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("ANOIFIG_DATABASE_URL", "private-database-url")
    monkeypatch.setenv("ANOIFIG_TWILIO_AUTH_TOKEN", "private-twilio-token")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-private-key")
    monkeypatch.setenv("OPENAI_LOG", "debug")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/reviewed/ca.pem")
    journal, _ = launch(monkeypatch, tmp_path, "malformed")
    with pytest.raises(ProviderFailure):
        OpenAIProvider(settings).respond(REQUEST)
    started = events(journal)[0]
    environment = started["environment_names"]
    assert started["synthetic_proxy_preserved"] and started["synthetic_ca_preserved"]
    assert not any(
        name in environment
        for name in (
            "ANOIFIG_DATABASE_URL",
            "ANOIFIG_TWILIO_AUTH_TOKEN",
            "OPENAI_API_KEY",
            "OPENAI_LOG",
            "PYTHONPATH",
        )
    )


def test_production_launcher_is_fixed_and_does_not_inherit_unreviewed_environment(
    monkeypatch, tmp_path
):
    captured = []

    def capture(*args, **kwargs):
        captured.append((args, kwargs))
        return object()

    monkeypatch.setenv("ANOIFIG_DATABASE_URL", "never-child-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://reviewed-proxy.invalid:8080")
    monkeypatch.setattr(provider_isolation.subprocess, "Popen", capture)
    with (tmp_path / "output").open("wb") as output:
        provider_isolation._start_child(output)
    args, options = captured[0]
    assert args[0] == [
        sys.executable,
        "-I",
        "-m",
        "anoifig.tara.provider_process",
        str(os.getpid()),
    ]
    assert options["stderr"] == subprocess.DEVNULL and options["close_fds"] is True
    assert "ANOIFIG_DATABASE_URL" not in options["env"]
    assert options["env"]["HTTPS_PROXY"] == "http://reviewed-proxy.invalid:8080"


def test_unsupported_parent_death_platform_fails_closed(settings, monkeypatch):
    monkeypatch.setattr(provider_isolation.sys, "platform", "unsupported")
    with pytest.raises(ProviderFailure):
        OpenAIProvider(settings).respond(REQUEST)


def test_input_bound_prevents_child_start(settings, monkeypatch):
    def unexpected_start(_):
        pytest.fail("Oversized payload must not start an SDK child")

    monkeypatch.setattr(provider_isolation, "_start_child", unexpected_start)
    with pytest.raises(ProviderFailure):
        OpenAIProvider(settings).respond(
            AIRequest({}, (), "x" * provider_isolation.MAX_INPUT_BYTES)
        )
