"""Linux request-child containment, including blocking DNS and SDK teardown."""

import json
import os
import subprocess  # nosec B404
import sys
import time
from contextlib import suppress
from dataclasses import asdict
from typing import BinaryIO

from pydantic import ValidationError

from anoifig.config import Settings
from anoifig.tara.provider import AIRequest, AIResult, ProviderFailure, ProviderResult

# Bounded cleanup is additional to the configured request deadline and remains
# well below the 120-second processing fence even at the 90-second maximum.
TERMINATE_SECONDS = 0.25
KILL_SECONDS = 0.25
MAX_INPUT_BYTES = 512 * 1024
MAX_OUTPUT_BYTES = 128 * 1024
_NETWORK_ENVIRONMENT = frozenset(
    {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "LANG",
        "LC_ALL",
    }
)


def _stop(child: subprocess.Popen[bytes]) -> None:
    """Never wait for asyncio executor shutdown, or wait indefinitely to reap."""
    try:
        _terminate(child)
    finally:
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                with suppress(OSError):
                    stream.close()


def _terminate(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is not None:
        return
    try:
        child.terminate()
    except ProcessLookupError:
        return
    try:
        child.wait(timeout=TERMINATE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            child.kill()
        except ProcessLookupError:
            return
        # SIGKILL cannot force an unscheduled/uninterruptible kernel task to be
        # reaped by a fixed instant. Do not pin the messaging worker to it.
        with suppress(subprocess.TimeoutExpired):
            child.wait(timeout=KILL_SECONDS)


def _payload(settings: Settings, request: AIRequest) -> bytes:
    key = settings.openai_api_key
    if key is None:
        raise ProviderFailure
    return json.dumps(
        {
            "configuration": {
                "api_key": key.get_secret_value(),
                "model": settings.tara_model,
                "timeout_seconds": settings.tara_timeout_seconds,
                "deadline_seconds": settings.tara_deadline_seconds,
                "max_retries": settings.tara_max_retries,
                "max_output_tokens": settings.tara_max_output_tokens,
            },
            "request": asdict(request),
        },
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _start_child(output: BinaryIO) -> subprocess.Popen[bytes]:
    # -I ignores PYTHONPATH/user site/current-directory imports. Only reviewed
    # networking trust/proxy settings survive; database and Twilio secrets do not.
    return subprocess.Popen(  # nosec B603
        [sys.executable, "-I", "-m", "anoifig.tara.provider_process", str(os.getpid())],
        stdin=subprocess.PIPE,
        stdout=output,
        stderr=subprocess.DEVNULL,
        env={name: value for name, value in os.environ.items() if name in _NETWORK_ENVIRONMENT},
        close_fds=True,
    )


def isolated_response(settings: Settings, request: AIRequest, *, started: float) -> AIResult:
    if sys.platform != "linux":
        # Parent-death signalling is part of the contract, not an optional guard.
        raise ProviderFailure
    child: subprocess.Popen[bytes] | None = None
    try:
        payload = _payload(settings, request)
        if len(payload) > MAX_INPUT_BYTES:
            raise ProviderFailure
        # An anonymous memory-only descriptor avoids an on-disk conversation copy
        # and communicate's unbounded stdout buffer. The trusted child caps its
        # output; the parent independently bounds/validates every result read.
        descriptor = os.memfd_create("tara-provider-result", flags=os.MFD_CLOEXEC)
        with os.fdopen(descriptor, "w+b") as output:
            child = _start_child(output)
            remaining = settings.tara_deadline_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise ProviderFailure
            child.communicate(payload, timeout=remaining)
            if (
                child.returncode != 0
                or time.monotonic() - started >= settings.tara_deadline_seconds
            ):
                raise ProviderFailure
            output.seek(0)
            result = output.read(MAX_OUTPUT_BYTES + 1)
            if len(result) > MAX_OUTPUT_BYTES:
                raise ProviderFailure
            return ProviderResult.model_validate_json(result).result()
    except (OSError, subprocess.SubprocessError, ValidationError, ValueError, TypeError):
        raise ProviderFailure from None
    finally:
        # Also runs for KeyboardInterrupt/SystemExit or another BaseException:
        # cancellation never leaves the SDK request child alive intentionally.
        if child is not None:
            _stop(child)
