"""Offline child harness: patches platform/HTTP boundaries, never application exits."""

import json
import os
import signal
import socket
import sys
import time
from pathlib import Path

from anoifig.tara.provider_process import main, protect_parent

scenario, journal_name, parent_pid = sys.argv[1:]
assert protect_parent(int(parent_pid))
journal = Path(journal_name)


def emit(event, **values):
    with journal.open("a") as stream:
        stream.write(json.dumps({"event": event, "pid": os.getpid(), **values}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


emit(
    "started",
    environment_names=list(os.environ),
    synthetic_proxy_preserved=os.environ.get("HTTPS_PROXY") == "http://proxy.invalid:8080",
    synthetic_ca_preserved=os.environ.get("SSL_CERT_FILE") == "/reviewed/ca.pem",
)

if scenario in {"dns", "dns_ignore_term"}:
    if scenario == "dns_ignore_term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    def stalled_resolver(*args, **kwargs):
        emit("dns_started")
        time.sleep(6)
        emit("dns_finished")
        return []  # No actual hostname lookup or connection.

    socket.getaddrinfo = stalled_resolver
elif scenario == "malformed":
    sys.stdout.write('{"private":"not a result"}')
    raise SystemExit(0)
elif scenario == "oversized":
    sys.stdout.write("x" * (128 * 1024 + 1))
    raise SystemExit(0)
else:
    import asyncio

    import httpx
    from openai import AsyncOpenAI

    import anoifig.tara.provider_transport as transport

    async def handler(request):
        emit("sdk_request", body=json.loads(request.content))
        if scenario == "retry":
            return httpx.Response(
                429,
                headers={"retry-after": "60"},
                json={"error": {"message": "synthetic private error", "type": "rate_limit"}},
            )
        if scenario == "late":
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                emit("async_cancelled")
                # Deliberately hostile transport ignores async cancellation.
                await asyncio.sleep(6)
            emit("late_result")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-offline",
                "object": "chat.completion",
                "created": 1,
                "model": "configured-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"intent": "general", "text": "Hello"}),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    def client(**kwargs):
        return AsyncOpenAI(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

    transport.AsyncOpenAI = client

sys.argv = [sys.argv[0], parent_pid]
raise SystemExit(main())
