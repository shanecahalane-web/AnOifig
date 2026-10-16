"""Synchronous worker boundary with cancellable, bounded asynchronous provider I/O."""

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI, OpenAIError, pydantic_function_tool
from pydantic import ValidationError

from anoifig.config import Settings
from anoifig.tara.prompt import INSTRUCTIONS
from anoifig.tara.schemas import Decision, Intent, ProposedNotes, Reply

TOOL_NAME = "propose_invoice_notes"


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
    def __init__(self, settings: Settings, *, client: AsyncOpenAI | None = None) -> None:
        if settings.openai_api_key is None:
            raise ValueError("OpenAI key is required")
        self.settings = settings
        self.client = client

    def respond(self, request: AIRequest) -> AIResult:
        try:
            return asyncio.run(self._respond(request))
        except (TimeoutError, OpenAIError, ValidationError, ValueError, IndexError, AttributeError):
            raise ProviderFailure from None

    async def _respond(self, request: AIRequest) -> AIResult:
        # Each synchronous call owns its event loop and client. Cancellation stops
        # SDK retry waits and HTTP I/O; no detached task can spend after fallback.
        key = self.settings.openai_api_key
        if key is None:
            raise ProviderFailure
        async with asyncio.timeout(self.settings.tara_deadline_seconds):
            async with self.client or AsyncOpenAI(
                api_key=key.get_secret_value(),
                timeout=self.settings.tara_timeout_seconds,
                max_retries=self.settings.tara_max_retries,
            ) as client:
                return await self._completion(client, request)

    async def _completion(self, client: AsyncOpenAI, request: AIRequest) -> AIResult:
        completion = await client.chat.completions.parse(
            model=self.settings.tara_model,
            messages=[
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": request.payload()},
            ],
            tools=[pydantic_function_tool(ProposedNotes, name=TOOL_NAME)],
            parallel_tool_calls=False,
            response_format=Reply,
            max_completion_tokens=self.settings.tara_max_output_tokens,
            store=False,
        )
        message = completion.choices[0].message
        if message.refusal or completion.choices[0].finish_reason not in {"stop", "tool_calls"}:
            raise ProviderFailure
        calls = message.tool_calls or []
        if calls:
            if len(calls) != 1 or calls[0].type != "function":
                raise ProviderFailure
            call = calls[0].function
            if call.name != TOOL_NAME or message.content:
                raise ProviderFailure
            decision = Decision(proposal=ProposedNotes.model_validate_json(call.arguments))
        else:
            if message.parsed is None:
                raise ProviderFailure
            decision = Decision(reply=message.parsed)
        usage = completion.usage
        if usage is None or usage.prompt_tokens < 0 or usage.completion_tokens < 0:
            raise ProviderFailure
        return AIResult(decision, usage.prompt_tokens, usage.completion_tokens)


def build_provider(settings: Settings) -> AIProvider:
    if settings.tara_mode == "openai":
        return OpenAIProvider(settings)
    if settings.tara_mode == "mock":
        return MockAIProvider()
    raise ValueError("acknowledgement mode does not use an AI provider")
