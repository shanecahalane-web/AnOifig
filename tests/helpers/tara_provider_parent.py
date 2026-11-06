"""Offline worker harness for SIGKILL/parent-death request containment tests."""

import os
import select
import subprocess
import sys
from pathlib import Path

from anoifig.config import Settings
from anoifig.tara import provider_isolation
from anoifig.tara.provider import AIRequest, OpenAIProvider

journal = sys.argv[1]
helper = Path(__file__).with_name("tara_provider_child.py")


def child(output):
    reader, writer = os.pipe()
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", str(helper), "dns", journal, str(os.getpid()), str(writer)],
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(writer,),
        )
        os.close(writer)
        writer = None
        if not select.select([reader], [], [], 20)[0] or os.read(reader, 1) != b"R":
            raise RuntimeError("Offline SDK fixture did not finish preparation")
        # Let the test start its unchanged DNS-entry window after cold setup.
        # The child still awaits the real adapter's payload on stdin.
        sys.stdout.buffer.write(b"R")
        sys.stdout.buffer.flush()
        return process
    except BaseException:
        if process is not None:
            provider_isolation._stop(process)
        raise
    finally:
        os.close(reader)
        if writer is not None:
            os.close(writer)


provider_isolation._start_child = child
settings = Settings(
    _env_file=None,
    environment="test",
    database_url="postgresql+psycopg://synthetic:private@localhost/anoifig_unit",
    tara_mode="openai",
    openai_api_key="synthetic-key-never-sent",
    tara_input_price_usd="1",
    tara_output_price_usd="4",
    tara_deadline_seconds=30,
)
OpenAIProvider(settings).respond(AIRequest({}, (), "Hello"))
