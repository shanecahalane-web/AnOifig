"""Offline worker harness for SIGKILL/parent-death request containment tests."""

import os
import subprocess
import sys
from pathlib import Path

from anoifig.config import Settings
from anoifig.tara import provider_isolation
from anoifig.tara.provider import AIRequest, OpenAIProvider

journal = sys.argv[1]
helper = Path(__file__).with_name("tara_provider_child.py")


def child(output):
    return subprocess.Popen(
        [sys.executable, "-I", str(helper), "dns", journal, str(os.getpid())],
        stdin=subprocess.PIPE,
        stdout=output,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


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
