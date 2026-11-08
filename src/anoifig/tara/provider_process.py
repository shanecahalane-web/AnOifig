"""Minimal Linux child launcher; do not import the SDK before parent protection."""

import ctypes
import os
import signal
import sys


def protect_parent(parent_pid: int) -> bool:
    """SIGKILL this interpreter, including resolver threads, if its parent dies."""
    if sys.platform != "linux":
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    # Linux prctl(PR_SET_PDEATHSIG, SIGKILL). No preexec_fn in a threaded parent.
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        return False
    # Close the race where the parent died before PR_SET_PDEATHSIG was installed.
    return os.getppid() == parent_pid


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit() or not protect_parent(int(sys.argv[1])):
        return 1

    import asyncio

    from anoifig.tara.provider import ProviderResult
    from anoifig.tara.provider_isolation import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES
    from anoifig.tara.provider_transport import (
        OpenAITransport,
        ProviderInvocation,
    )

    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            return 1
        invocation = ProviderInvocation.model_validate_json(raw)
        result = asyncio.run(OpenAITransport(invocation.configuration).respond(invocation.request))
        output = (
            ProviderResult(
                decision=result.decision,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            .model_dump_json()
            .encode()
        )
        if len(output) > MAX_OUTPUT_BYTES:
            return 1
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
    except Exception:
        # SDK/validation/transport errors are deliberately content-free across
        # IPC. The parent records one safe provider failure and keeps reservations.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
