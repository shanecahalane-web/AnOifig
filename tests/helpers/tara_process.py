"""Test-only real process that pauses after the durable AI reservation commits."""

import json
import sys
from uuid import UUID

from anoifig.config import Settings
from anoifig.db.session import build_engine
from anoifig.messaging.provider import LocalMessagingProvider
from anoifig.messaging.worker import MessagingWorker
from anoifig.tara.provider import MockAIProvider


class PausedAI(MockAIProvider):
    def respond(self, request):
        print(json.dumps({"event": "ai_called_after_reservation"}), flush=True)
        sys.stdin.readline()
        raise RuntimeError("Test parent must kill the paused process")


def main():
    config = json.loads(sys.stdin.readline())
    settings = Settings(_env_file=None, **config["settings"])
    assert settings.environment == "test" and settings.tara_mode == "mock"
    engine = build_engine(settings)
    try:
        MessagingWorker(
            engine, settings, LocalMessagingProvider(), ai_provider=PausedAI()
        ).process_delivery(UUID(config["job_id"]))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"event": "failed", "error_type": type(error).__name__}), flush=True)
        sys.exit(1)
