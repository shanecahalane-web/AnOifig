"""Fenced, ordered orchestration. Provider I/O runs outside all DB transactions."""

import json
import logging
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_UP, Decimal
from uuid import UUID, uuid4

from sqlalchemy import Engine, literal, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from anoifig.config import Settings
from anoifig.db.messaging_models import Conversation, Message, Outbox
from anoifig.db.session import check_runtime_database
from anoifig.db.tara_models import TaraPendingProposal, TaraRun, TaraState, TaraUsage
from anoifig.identity.service import AccessDenied
from anoifig.messaging.service import Job, authorise_route, reply_to_inbound
from anoifig.tara.privacy import (
    CONFIRMATION,
    OMITTED_CONFIRMATION,
    is_confirmation_shaped,
    minimise,
)
from anoifig.tara.prompt import INSTRUCTIONS, PROMPT_VERSION
from anoifig.tara.provider import AIProvider, AIRequest, AIResult
from anoifig.tara.schemas import (
    Decision,
    Intent,
    InvoiceNotes,
    PendingClarification,
    ProposedNotes,
    Reply,
    apply_proposal,
    render_notes,
)

logger = logging.getLogger(__name__)
FALLBACK = (
    "I'm having trouble with that message. Your existing notes are saved. Please try again shortly."
)
INVALID = (
    "I couldn't safely interpret those details. "
    "What correction, amount or VAT treatment should I record? "
    "Your existing notes are saved."
)
BUDGET = (
    "I've reached this business's AI limit for today. Your existing notes are saved. "
    "Please try again tomorrow."
)
CAPABILITIES = (
    "I can help collect and correct information for an invoice. Creating or sending invoices, "
    "PDFs, quotations, payments, expenses and reminders aren't available yet."
)
FORGET_COMMANDS = {"forget my notes", "clear my notes", "start a new invoice", "start over"}


def proposal_preview(before: dict[str, object], after: dict[str, object], challenge: str) -> str:
    def quoted(value: object) -> str:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return "".join(
            json.dumps(char, ensure_ascii=True)[1:-1]
            if unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            else char
            for char in rendered
        )

    lines = ["Proposed changes (not saved):"]
    for field in sorted(before):
        if before[field] != after[field]:
            old = quoted(before[field])
            new = quoted(after[field])
            lines.append(f"{field}: {old} → {new}")
    lines.append(f"Reply APPLY {challenge} to save, or REJECT {challenge} to discard.")
    preview = "\n".join(lines)
    if len(preview) > 1600 or "\x00" in preview:
        raise ValueError("proposal preview too long")
    return preview


@dataclass(frozen=True)
class Command:
    job: Job
    message_id: UUID
    token: UUID
    request: AIRequest
    expected_version: int


class TaraService:
    def __init__(self, engine: Engine, settings: Settings, provider: AIProvider) -> None:
        self.engine, self.settings, self.provider = engine, settings, provider

    def _authorise(self, session: Session, job: Job, *, lock_link: bool = False) -> None:
        check_runtime_database(
            session.connection(), require_tls=self.settings.environment == "production"
        )
        authorise_route(session, job.route, lock_link=lock_link)

    def process(self, job: Job) -> bool:
        prepared = self._prepare(job)
        if isinstance(prepared, bool):
            return prepared
        result: AIResult | None = None
        error: str | None = None
        try:
            result = self.provider.respond(prepared.request)
        except Exception:
            # SDK exceptions can contain request text, URLs or secrets.
            error = "provider_failed"
            logger.warning("Tara provider failed", extra={"event": "tara_provider_failed"})
        return self._complete(prepared, result, error)

    def _prepare(self, job: Job) -> Command | bool:
        with Session(self.engine) as session, session.begin():
            self._authorise(session, job)
            message = session.scalar(
                select(Message).where(
                    Message.tenant_id == job.route.tenant_id,
                    Message.id == job.entity_id,
                    Message.direction == "inbound",
                )
            )
            if message is None:
                return True
            # Lock the conversation before its messages, matching ingress lock order.
            conversation = session.scalar(
                select(Conversation)
                .where(
                    Conversation.tenant_id == message.tenant_id,
                    Conversation.id == message.conversation_id,
                )
                .with_for_update(skip_locked=True)
            )
            if conversation is None:
                return False
            session.refresh(message, with_for_update=True)
            now = datetime.now(UTC)
            if message.processed_at is not None:
                return True
            first = session.scalar(
                select(Message.id)
                .where(
                    Message.tenant_id == message.tenant_id,
                    Message.conversation_id == message.conversation_id,
                    Message.direction == "inbound",
                    Message.processed_at.is_(None),
                )
                .order_by(Message.received_at, Message.id)
                .limit(1)
            )
            if first != message.id or message.available_at > now:
                return False
            # A redelivery must be read-only while the original turn owns its
            # run. In particular, it must not expire memory or advance the
            # version captured by an in-flight provider request.
            run = session.get(TaraRun, message.id)
            if run is not None:
                if run.status == "complete":
                    return True
                if run.expires_at > now:
                    return False
            state = session.get(TaraState, conversation.id)
            if state is None:
                state = TaraState(
                    conversation_id=conversation.id,
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    notes={},
                    version=0,
                    memory_since=message.received_at,
                    updated_at=now,
                )
                session.add(state)
                session.flush()
            if state.user_id != message.user_id:
                raise AccessDenied
            confirmation = CONFIRMATION.fullmatch(message.body)
            sensitive = is_confirmation_shaped(message.body)
            memory_expired = min(state.updated_at, state.memory_since) < now - timedelta(
                days=self.settings.tara_memory_days
            )
            if memory_expired and not sensitive:
                self._clear_memory(session, state, message)
            if run is not None:
                self._finish(session, message, state, run, FALLBACK, "processing_interrupted")
                return True
            if confirmation is not None:
                return self._confirmation(
                    session, job, message, state, confirmation, now, memory_expired=memory_expired
                )
            run = TaraRun(
                message_id=message.id,
                tenant_id=message.tenant_id,
                conversation_id=conversation.id,
                user_id=message.user_id,
                token=uuid4(),
                expires_at=now + timedelta(minutes=2),
                status="processing",
                model=self.settings.tara_model if self.settings.tara_mode == "openai" else "mock",
                prompt_version=PROMPT_VERSION,
                started_at=now,
                usage_day=now.date(),
                reserved_tokens=0,
                reserved_cost=Decimal("0"),
                expected_version=state.version,
            )
            session.add(run)
            if sensitive:
                run.action = "proposal_unavailable"
                self._finish(
                    session,
                    message,
                    state,
                    run,
                    "Please send the exact APPLY or REJECT command from the preview.",
                    None,
                )
                return True
            if message.body.strip().casefold() in FORGET_COMMANDS:
                self._clear_memory(session, state, message)
                run.action = "memory_cleared"
                self._finish(
                    session,
                    message,
                    state,
                    run,
                    "I've cleared the preparation notes and conversation context. "
                    "What would you like to work on?",
                    None,
                )
                return True
            try:
                notes = InvoiceNotes.model_validate(state.notes)
            except ValueError:
                self._clear_memory(session, state, message)
                self._finish(session, message, state, run, INVALID, "state_invalid")
                return True
            history = self._history(session, message, state, notes, now)
            provider_notes = notes.model_dump(mode="json", exclude={"customer_details"})
            # Contact fields can appear in other free-text note fields too.
            for field, value in provider_notes.items():
                if isinstance(value, str):
                    provider_notes[field] = minimise(value, contact_details=notes.customer_details)
            for item in provider_notes["line_items"]:
                item["description"] = minimise(
                    item["description"], contact_details=notes.customer_details
                )
            request = AIRequest(
                provider_notes, history, message.body, state.version, state.pending_clarification
            )
            while self._input_bound(request) > self.settings.tara_max_input_tokens and history:
                history = history[1:]
                request = AIRequest(
                    provider_notes,
                    history,
                    message.body,
                    state.version,
                    state.pending_clarification,
                )
            if self._input_bound(request) > self.settings.tara_max_input_tokens:
                self._finish(session, message, state, run, INVALID, "context_limit")
                return True
            if not self._reserve(session, run):
                self._finish(session, message, state, run, BUDGET, "budget_exceeded")
                return True
            return Command(job, message.id, run.token, request, state.version)

    @staticmethod
    def _clear_memory(session: Session, state: TaraState, message: Message) -> None:
        pending = session.scalar(
            select(TaraPendingProposal)
            .where(
                TaraPendingProposal.conversation_id == state.conversation_id,
                TaraPendingProposal.tenant_id == state.tenant_id,
                TaraPendingProposal.status == "pending",
            )
            .with_for_update()
        )
        if pending is not None:
            pending.status = "superseded"
        # Acceptance position is durable even if following messages are already queued.
        state.notes, state.pending_clarification = {}, None
        state.memory_since, state.memory_after_id = message.received_at, message.id
        state.updated_at = datetime.now(UTC)
        state.version += 1

    def _confirmation(
        self,
        session: Session,
        job: Job,
        message: Message,
        state: TaraState,
        command: re.Match[str],
        now: datetime,
        *,
        memory_expired: bool,
    ) -> bool:
        proposal = session.scalar(
            select(TaraPendingProposal)
            .where(
                TaraPendingProposal.tenant_id == message.tenant_id,
                TaraPendingProposal.user_id == message.user_id,
                TaraPendingProposal.conversation_id == message.conversation_id,
                TaraPendingProposal.challenge == command.group(2),
                TaraPendingProposal.status == "pending",
            )
            .with_for_update()
        )
        body = "That proposal is no longer available. Please send the changes again."
        action = "proposal_unavailable"
        preview = None
        if (
            proposal is not None
            and proposal.expires_at > now
            and not memory_expired
            and proposal.expected_version == state.version
        ):
            # The preview is the unique reply/outbox of the originating turn.
            preview = session.execute(
                select(Message, Outbox)
                .join(
                    Outbox,
                    (Outbox.message_id == Message.id) & (Outbox.tenant_id == Message.tenant_id),
                )
                .where(
                    Message.tenant_id == message.tenant_id,
                    Message.reply_to_id == proposal.source_message_id,
                )
                .with_for_update(of=Outbox)
            ).one_or_none()
            if preview is not None:
                session.refresh(preview[0], with_for_update=True)
        # Lock the link after the conversation and any preview locks. Unlink
        # only locks the link, so it cannot wait on these rows while holding it.
        session.expire_all()
        self._authorise(session, job, lock_link=True)
        checked_at = datetime.now(UTC)
        if proposal is not None and proposal.expires_at <= checked_at:
            proposal.status = "expired"
        elif proposal is not None and (
            memory_expired
            or proposal.expected_version != state.version
            or min(state.updated_at, state.memory_since)
            < checked_at - timedelta(days=self.settings.tara_memory_days)
        ):
            proposal.status = "superseded"
        elif proposal is not None:
            if preview is None:
                raise ValueError("missing proposal preview")
            preview_message, outbox = preview
            source = session.get(Message, proposal.source_message_id)
            if (
                source is None
                or (message.received_at, message.id)
                <= (
                    source.received_at,
                    source.id,
                )
                or preview_message.body
                != proposal_preview(proposal.before_notes, proposal.after_notes, proposal.challenge)
            ):
                proposal.status = "superseded"
            elif outbox.status in {"pending", "retry", "dispatching", "uncertain"}:
                return False
            elif outbox.status != "sent" or preview_message.status in {
                "failed",
                "canceled",
                "undelivered",
                "blocked",
            }:
                proposal.status = "superseded"
            elif command.group(1) == "REJECT":
                proposal.status = "rejected"
                proposal.confirmation_message_id = message.id
                body, action = (
                    "The proposed changes were rejected. Your notes are unchanged.",
                    "proposal_rejected",
                )
            elif (
                InvoiceNotes.model_validate(state.notes).model_dump(mode="json")
                != proposal.before_notes
            ):
                proposal.status = "superseded"
            else:
                notes = InvoiceNotes.model_validate(proposal.after_notes)
                state.notes = notes.model_dump(mode="json")
                state.version += 1
                state.pending_clarification = self._pending(notes)
                proposal.status = "confirmed"
                proposal.confirmation_message_id = message.id
                body = render_notes(notes, correction=True)
                action = (
                    "contact_proposal_confirmed"
                    if proposal.before_notes.get("customer_details")
                    != proposal.after_notes.get("customer_details")
                    else "proposal_confirmed"
                )
        run = TaraRun(
            message_id=message.id,
            tenant_id=message.tenant_id,
            conversation_id=message.conversation_id,
            user_id=message.user_id,
            token=uuid4(),
            expires_at=now + timedelta(minutes=2),
            status="processing",
            model="application",
            prompt_version=PROMPT_VERSION,
            started_at=now,
            usage_day=now.date(),
            reserved_tokens=0,
            reserved_cost=Decimal("0"),
            expected_version=state.version,
            action=action,
        )
        session.add(run)
        self._finish(session, message, state, run, body, None)
        return True

    def _history(
        self,
        session: Session,
        message: Message,
        state: TaraState,
        notes: InvoiceNotes,
        now: datetime,
    ) -> tuple[dict[str, str], ...]:
        if not self.settings.tara_history_messages:
            return ()
        query = (
            select(Message, TaraRun.intent, TaraRun.action)
            .outerjoin(
                TaraRun,
                (TaraRun.message_id == Message.id) & (TaraRun.tenant_id == Message.tenant_id),
            )
            .where(
                Message.tenant_id == message.tenant_id,
                Message.conversation_id == message.conversation_id,
                Message.direction == "inbound",
                Message.processed_at.is_not(None),
                Message.body != OMITTED_CONFIRMATION,
                # Successful structured edits are already represented by the
                # validated notes. Never replay their raw text, including old
                # contact corrections recorded before contact-specific audit
                # metadata existed. This rule does not rely on model intent.
                (TaraRun.action.is_(None))
                | (
                    TaraRun.action.not_in(
                        (
                            "notes_merged",
                            "contact_notes_merged",
                            "proposal_pending",
                            "proposal_noop",
                            "proposal_confirmed",
                            "contact_proposal_confirmed",
                            "proposal_rejected",
                            "proposal_unavailable",
                        )
                    )
                ),
                Message.received_at >= now - timedelta(days=self.settings.tara_memory_days),
                tuple_(Message.received_at, Message.id)
                < tuple_(literal(message.received_at), literal(message.id)),
            )
        )
        if state.memory_after_id is not None:
            query = query.where(
                tuple_(Message.received_at, Message.id)
                > tuple_(literal(state.memory_since), literal(state.memory_after_id))
            )
        else:
            query = query.where(Message.received_at >= state.memory_since)
        rows = list(
            session.execute(
                query.order_by(Message.received_at.desc(), Message.id.desc()).limit(
                    self.settings.tara_history_messages
                )
            )
        )
        # Structured notes and pending clarification carry application state. Replaying
        # outbound prose adds PII and stale financial questions without new facts.
        return tuple(
            {
                "role": "inbound",
                "text": (
                    "[customer contact turn omitted]"
                    if intent == "customer_information"
                    else minimise(row.body, contact_details=notes.customer_details)[:600]
                ),
            }
            for row, intent, _action in reversed(rows)
            # Legacy and recovery records can lack an action tag.
            if not is_confirmation_shaped(row.body)
        )

    @staticmethod
    def _pending(notes: InvoiceNotes) -> PendingClarification | None:
        if not notes.customer_name or (not notes.work_description and not notes.line_items):
            return None
        if not notes.line_items and not any(
            value is not None for value in (notes.amount, notes.labour, notes.materials)
        ):
            return None
        if notes.vat_basis is None:
            return "vat_basis"
        if notes.vat_basis != "no_vat" and notes.vat_rate is None:
            return "vat_rate"
        return None

    @staticmethod
    def _input_bound(request: AIRequest) -> int:
        # UTF-8 bytes conservatively bound normal tokenizer content, plus schema
        # bytes and framing allowance. Provider-reported usage is checked too.
        schemas = json.dumps([ProposedNotes.model_json_schema(), Reply.model_json_schema()])
        return len((INSTRUCTIONS + request.payload() + schemas).encode("utf-8")) + 2048

    def _cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            (
                Decimal(input_tokens) * self.settings.tara_input_price_usd
                + Decimal(output_tokens) * self.settings.tara_output_price_usd
            )
            / 1000000
        ).quantize(Decimal("0.00000001"), rounding=ROUND_UP)

    def _reserve(self, session: Session, run: TaraRun) -> bool:
        session.execute(
            insert(TaraUsage)
            .values(tenant_id=run.tenant_id, day=run.usage_day)
            .on_conflict_do_nothing()
        )
        usage = session.scalar(
            select(TaraUsage)
            .where(
                TaraUsage.tenant_id == run.tenant_id,
                TaraUsage.day == run.usage_day,
            )
            .with_for_update()
        )
        if usage is None:
            raise AccessDenied
        attempts = self.settings.tara_max_retries + 1
        tokens = (
            self.settings.tara_max_input_tokens + self.settings.tara_max_output_tokens
        ) * attempts
        cost = (
            self._cost(self.settings.tara_max_input_tokens, self.settings.tara_max_output_tokens)
            * attempts
        )
        budget = self.settings.tara_business_budgets.get(
            run.tenant_id, self.settings.tara_daily_budget
        )
        if (
            usage.requests + attempts > budget.requests
            or usage.tokens + tokens > budget.tokens
            or usage.cost_usd + cost > budget.cost_usd
        ):
            return False
        usage.requests += attempts
        usage.tokens += tokens
        usage.cost_usd += cost
        run.reserved_tokens, run.reserved_cost = tokens, cost
        return True

    def _complete(self, command: Command, result: AIResult | None, error: str | None) -> bool:
        with Session(self.engine) as session, session.begin():
            self._authorise(session, command.job)
            conversation = session.scalar(
                select(Conversation)
                .where(
                    Conversation.tenant_id == command.job.route.tenant_id,
                    Conversation.id
                    == select(Message.conversation_id)
                    .where(
                        Message.id == command.message_id,
                        Message.tenant_id == command.job.route.tenant_id,
                    )
                    .scalar_subquery(),
                )
                .with_for_update()
            )
            if conversation is None:
                raise AccessDenied
            message = session.get(Message, command.message_id, with_for_update=True)
            run = session.get(TaraRun, command.message_id, with_for_update=True)
            state = session.get(TaraState, conversation.id)
            if message is None or run is None or state is None:
                raise AccessDenied
            if (
                message.processed_at is not None
                or run.status != "processing"
                or run.token != command.token
            ):
                return True
            if run.expires_at <= datetime.now(UTC):
                result, error = None, "processing_interrupted"
            if (
                state.version != command.expected_version
                or run.expected_version != command.expected_version
            ):
                result, error = None, "stale_state"
            body = FALLBACK
            if result is not None:
                try:
                    body = self._apply(session, command.job, message, state, run, result)
                except (ValueError, TypeError, AttributeError):
                    error, body = "invalid_model_response", INVALID
            self._finish(session, message, state, run, body, error)
            return True

    def _apply(
        self,
        session: Session,
        job: Job,
        message: Message,
        state: TaraState,
        run: TaraRun,
        result: AIResult,
    ) -> str:
        # Revalidate even injected providers. Exactly one structured outcome.
        decision = Decision.model_validate(result.decision.model_dump())
        if (
            result.input_tokens < 0
            or result.output_tokens < 0
            or result.input_tokens > self.settings.tara_max_input_tokens
            or result.output_tokens > self.settings.tara_max_output_tokens
            or (decision.reply is None) == (decision.proposal is None)
        ):
            raise ValueError("invalid provider result")
        run.input_tokens, run.output_tokens = result.input_tokens, result.output_tokens
        run.estimated_cost = self._cost(result.input_tokens, result.output_tokens)
        if decision.proposal is not None:
            # This is the complete action allowlist. No model-supplied IDs or SQL.
            authorise_route(session, job.route)
            before = InvoiceNotes.model_validate(state.notes)
            notes = apply_proposal(
                before,
                decision.proposal,
                message.body,
                pending_clarification=self._validated_pending(state.pending_clarification),
                expected_version=run.expected_version,
                current_version=state.version,
            )
            previous, proposed = before.model_dump(mode="json"), notes.model_dump(mode="json")
            if previous == proposed:
                run.action = "proposal_noop"
                state.pending_clarification = self._pending(before)
                return render_notes(before)
            challenge = secrets.token_hex(16).upper()
            preview = proposal_preview(previous, proposed, challenge)
            now = datetime.now(UTC)
            pending = session.scalar(
                select(TaraPendingProposal)
                .where(
                    TaraPendingProposal.tenant_id == state.tenant_id,
                    TaraPendingProposal.conversation_id == state.conversation_id,
                    TaraPendingProposal.status == "pending",
                )
                .with_for_update()
            )
            if pending is not None:
                pending.status = "expired" if pending.expires_at <= now else "superseded"
                session.flush()
            session.add(
                TaraPendingProposal(
                    id=uuid4(),
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    conversation_id=message.conversation_id,
                    source_message_id=message.id,
                    expected_version=state.version,
                    before_notes=previous,
                    after_notes=proposed,
                    challenge=challenge,
                    status="pending",
                    created_at=now,
                    expires_at=now + timedelta(hours=24),
                )
            )
            run.intent = decision.proposal.intent
            run.action = "proposal_pending"
            return preview
        if decision.reply is None:
            raise ValueError("missing structured reply")
        run.intent, run.action = decision.reply.intent.value, "reply"
        if decision.reply.intent in {Intent.UNSUPPORTED, Intent.FUNCTIONALITY}:
            state.pending_clarification = None
            return CAPABILITIES
        if decision.reply.intent == Intent.CLARIFICATION:
            state.pending_clarification = None
            return INVALID
        if decision.reply.intent != Intent.GENERAL:
            notes = InvoiceNotes.model_validate(state.notes)
            state.pending_clarification = self._pending(notes)
            return render_notes(notes)
        # Only backend-supported speech acts are rendered. Model prose is never
        # evidence that any business operation happened.
        state.pending_clarification = None
        return {
            "greeting": "Hi! What can I help you prepare today?",
            "thanks": "You're welcome. Let me know if you'd like to add or correct anything.",
            "check_in": "I'm here and ready to help. What would you like to work on?",
            "acknowledgement": "Okay. You can add details or tell me what needs correcting.",
            "help": (
                "Ready to help. I can collect and correct invoice preparation notes. "
                "What would you like to work on?"
            ),
        }[decision.reply.social_act]

    @staticmethod
    def _validated_pending(value: str | None) -> PendingClarification | None:
        if value in {"vat_basis", "vat_rate"}:
            return "vat_basis" if value == "vat_basis" else "vat_rate"
        return None

    def complete_processing_failure(self, session: Session, job: Job, message: Message) -> None:
        """Terminal bounded recovery; caller holds conversation then source locks.

        Never re-invoke the provider or refund a committed/ambiguous reservation.
        Completing the run fences any in-flight result, even before its deadline.
        """
        self._authorise(session, job)
        attempts = message.processing_attempts
        state = session.get(TaraState, message.conversation_id)
        now = datetime.now(UTC)
        if state is None:
            state = TaraState(
                conversation_id=message.conversation_id,
                tenant_id=message.tenant_id,
                user_id=message.user_id,
                notes={},
                version=0,
                memory_since=message.received_at,
                updated_at=now,
            )
            session.add(state)
        if state.user_id != message.user_id:
            raise AccessDenied
        run = session.get(TaraRun, message.id, with_for_update=True)
        if run is None:
            run = TaraRun(
                message_id=message.id,
                tenant_id=message.tenant_id,
                conversation_id=message.conversation_id,
                user_id=message.user_id,
                token=uuid4(),
                expires_at=now,
                status="processing",
                model=self.settings.tara_model if self.settings.tara_mode == "openai" else "mock",
                prompt_version=PROMPT_VERSION,
                started_at=now,
                usage_day=now.date(),
                reserved_tokens=0,
                reserved_cost=Decimal("0"),
                expected_version=state.version,
            )
            session.add(run)
        self._finish(session, message, state, run, FALLBACK, "processing_failed")
        message.processing_attempts = attempts

    @staticmethod
    def _finish(
        session: Session,
        message: Message,
        state: TaraState,
        run: TaraRun,
        body: str,
        error: str | None,
    ) -> None:
        now = datetime.now(UTC)
        run.status, run.completed_at, run.error_code = "complete", now, error
        if is_confirmation_shaped(message.body):
            message.body = OMITTED_CONFIRMATION
            if run.action is None:
                run.action = "proposal_unavailable"
        # A stale run owns its fallback reply, not the newer state's pending
        # question or activity timestamp. Keep every newer state field intact.
        if error != "stale_state":
            if error:
                state.pending_clarification = None
            state.updated_at = now
        message.conversation_version = state.version
        reply_to_inbound(
            session, message, body, error_code=error, conversation_version=state.version
        )
        if error:
            logger.info(
                "Tara turn completed with fallback",
                extra={"event": "tara_fallback", "reason": error},
            )
