"""Provider contracts and the synchronous, process-isolated worker boundary."""

import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from anoifig.config import Settings
from anoifig.tara.schemas import Decision, Intent, Reply


class ProviderFailure(Exception):
    """Safe error category only: never persist or log raw SDK exceptions."""


@dataclass(frozen=True)
class AIRequest:
    notes: dict[str, object]
    history: tuple[dict[str, str], ...]
    message: str
    state_version: int = 0
    pending_clarification: str | None = None

    def payload(self) -> str:
        return json.dumps(
            {
                "notes": self.notes,
                "history": self.history,
                "current_message": self.message,
                "state_version": self.state_version,
                "pending_clarification": self.pending_clarification,
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class AIResult:
    decision: Decision
    input_tokens: int
    output_tokens: int


class ProviderResult(BaseModel):
    """Strict child result, independent of the SDK's process/import lifecycle."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    decision: Decision
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    def result(self) -> AIResult:
        return AIResult(self.decision, self.input_tokens, self.output_tokens)


class AIProvider(Protocol):
    def respond(self, request: AIRequest) -> AIResult: ...


class MockAIProvider:
    """Explicit scripted transport, including failures, for offline tests/replays."""

    def __init__(self, results: list[AIResult | Exception] | None = None) -> None:
        self.results = deque(results or [])
        self.requests: list[AIRequest] = []

    def respond(self, request: AIRequest) -> AIResult:
        self.requests.append(request)
        if not self.results:
            return AIResult(
                Decision(reply=Reply(intent=Intent.GENERAL, text="How can I help?")), 0, 0
            )
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class OpenAIProvider:
    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise ValueError("OpenAI key is required")
        self.settings = settings

    def respond(self, request: AIRequest) -> AIResult:
        started = time.monotonic()
        # Import here so the minimal child launcher can set its Linux parent-death
        # signal before importing SDK/Pydantic/application modules.
        from anoifig.tara.provider_isolation import isolated_response

        return isolated_response(self.settings, request, started=started)


def build_provider(settings: Settings) -> AIProvider:
    if settings.tara_mode == "openai":
        return OpenAIProvider(settings)
    if settings.tara_mode == "mock":
        return MockAIProvider()
    raise ValueError("acknowledgement mode does not use an AI provider")
