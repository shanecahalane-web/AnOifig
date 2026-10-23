"""Async SDK component: process isolation, not cancellation, bounds its lifetime.

Only the request child (or offline component tests) calls this module directly.
In particular asyncio.run() may wait for uncancellable resolver executor work.
"""

import asyncio

from openai import AsyncOpenAI, pydantic_function_tool
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from anoifig.tara.prompt import INSTRUCTIONS
from anoifig.tara.provider import AIRequest, AIResult, ProviderFailure
from anoifig.tara.schemas import Decision, ProposedNotes, Reply

TOOL_NAME = "propose_invoice_notes"


class ProviderConfiguration(BaseModel):
    """Only the configuration needed by the SDK; no database/service credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    api_key: SecretStr
    model: str = Field(min_length=1, max_length=100)
    timeout_seconds: int = Field(ge=1, le=30)
    deadline_seconds: int = Field(ge=1, le=90)
    max_retries: int = Field(ge=0, le=2)
    max_output_tokens: int = Field(ge=128, le=4000)


class ProviderInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    configuration: ProviderConfiguration
    request: AIRequest


class OpenAITransport:
    """Async serializer/parser; its caller must supply process-level containment."""

    def __init__(
        self, configuration: ProviderConfiguration, *, client: AsyncOpenAI | None = None
    ) -> None:
        self.configuration = configuration
        self.client = client

    async def respond(self, request: AIRequest) -> AIResult:
        config = self.configuration
        async with asyncio.timeout(config.deadline_seconds):
            async with self.client or AsyncOpenAI(
                api_key=config.api_key.get_secret_value(),
                timeout=config.timeout_seconds,
                max_retries=config.max_retries,
            ) as client:
                return await self._completion(client, request)

    async def _completion(self, client: AsyncOpenAI, request: AIRequest) -> AIResult:
        config = self.configuration
        completion = await client.chat.completions.parse(
            model=config.model,
            messages=[
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": request.payload()},
            ],
            tools=[pydantic_function_tool(ProposedNotes, name=TOOL_NAME)],
            parallel_tool_calls=False,
            response_format=Reply,
            max_completion_tokens=config.max_output_tokens,
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
