"""Separate worker process: durable commands, transactional outbox, bounded retries."""

import argparse
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from anoifig.config import Settings, get_settings
from anoifig.db.messaging_models import Conversation, Message, Outbox
from anoifig.db.session import build_engine, check_runtime_database
from anoifig.identity.service import AccessDenied
from anoifig.messaging.delivery import advance_status, callback_url
from anoifig.messaging.provider import (
    AmbiguousFailure,
    LocalMessagingProvider,
    MessagingProvider,
    PermanentFailure,
    SafeRetry,
    SendResult,
    TwilioMessagingProvider,
)
from anoifig.messaging.queue import PostgresWorkQueue, WorkQueue
from anoifig.messaging.service import TARA_RESPONSE, Job, authorise_route, lookup_job

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
DISPATCH_LEASE = timedelta(minutes=2)


@dataclass(frozen=True)
class SendCommand:
    job: Job
    to: str
    body: str
    callback: str


class MessagingWorker:
    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        provider: MessagingProvider,
        queue: WorkQueue | None = None,
    ) -> None:
        self.engine, self.settings, self.provider = engine, settings, provider
        self.queue = queue if queue is not None else PostgresWorkQueue(engine, settings)

    def _check(self, session: Session) -> None:
        check_runtime_database(
            session.connection(),
            require_tls=self.settings.environment == "production",
        )

    def run_once(self) -> int:
        deliveries = self.queue.receive()
        for delivery in deliveries:
            try:
                self.process_delivery(delivery.id)
            except SQLAlchemyError:
                # Never print a driver/provider exception, its parameters or a DSN.
                logger.warning("Messaging database operation unavailable")
                self.queue.abandon(delivery)
            else:
                # Settlement follows committed database effects. The database
                # discovery implementation needs no separate acknowledgement.
                self.queue.complete(delivery)
        return len(deliveries)

    def process_delivery(self, job_id: UUID) -> None:
        try:
            self._process_delivery(job_id)
        except AccessDenied:
            # Also covers revocation during the provider call or failure recording.
            # Revocation forbids writing content; only park operational metadata.
            with Session(self.engine) as session, session.begin():
                self._check(session)
                session.execute(text("SELECT public.messaging_park_job(:id)"), {"id": job_id})

    def _process_delivery(self, job_id: UUID) -> None:
        job: Job | None = None
        command: SendCommand | None = None
        try:
            with Session(self.engine) as session, session.begin():
                self._check(session)
                job = lookup_job(session, job_id)
                if job is None:
                    return
                authorise_route(session, job.route)
                if job.kind == "inbound":
                    self._process_inbound(session, job)
                else:
                    command = self._prepare_outbound(session, job)
        except AccessDenied:
            raise
        except SQLAlchemyError:
            if job is not None and job.kind == "inbound":
                self._record_processing_failure(job)
                return
            raise
        except Exception:
            if job is not None and job.kind == "inbound":
                self._record_processing_failure(job)
                return
            raise
        if command is not None:
            self._send(command)

    def _process_inbound(self, session: Session, job: Job) -> None:
        message = session.scalar(
            select(Message)
            .where(
                Message.id == job.entity_id,
                Message.tenant_id == job.route.tenant_id,
                Message.direction == "inbound",
            )
            .with_for_update(skip_locked=True)
        )
        now = datetime.now(UTC)
        if message is None or message.processed_at is not None or message.available_at > now:
            return
        # Message lock serialises at-least-once deliveries. The unique reply FK
        # also prevents a second logical response after a lost acknowledgement.
        existing = session.scalar(
            select(Message.id).where(
                Message.tenant_id == job.route.tenant_id,
                Message.reply_to_id == message.id,
            )
        )
        if existing is None:
            response = Message(
                id=uuid4(),
                tenant_id=message.tenant_id,
                conversation_id=message.conversation_id,
                phone_link_id=message.phone_link_id,
                user_id=message.user_id,
                direction="outbound",
                body=TARA_RESPONSE,
                account_sid=message.account_sid,
                status="pending",
                reply_to_id=message.id,
            )
            session.add(response)
            session.flush()
            session.add(
                Outbox(
                    id=uuid4(),
                    tenant_id=message.tenant_id,
                    message_id=response.id,
                    phone_link_id=job.route.link_id,
                )
            )
        message.processed_at = now
        message.status = "processed"
        message.processing_attempts += 1
        message.processing_error = None

    def _record_processing_failure(self, job: Job) -> None:
        with Session(self.engine) as session, session.begin():
            self._check(session)
            authorise_route(session, job.route)
            message = session.scalar(
                select(Message)
                .where(
                    Message.id == job.entity_id,
                    Message.tenant_id == job.route.tenant_id,
                )
                .with_for_update()
            )
            if message is None or message.processed_at is not None:
                return
            message.processing_attempts += 1
            message.processing_error = "processing_failed"
            if message.processing_attempts >= MAX_ATTEMPTS:
                message.processed_at = datetime.now(UTC)
                message.status = "failed"
            else:
                message.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(3600, 2**message.processing_attempts),
                )

    def _prepare_outbound(self, session: Session, job: Job) -> SendCommand | None:
        _, link = authorise_route(session, job.route)
        outbox = session.scalar(
            select(Outbox)
            .where(
                Outbox.id == job.entity_id,
                Outbox.tenant_id == job.route.tenant_id,
            )
            .with_for_update(skip_locked=True)
        )
        if outbox is None:
            return None
        message = session.scalar(
            select(Message)
            .where(
                Message.id == outbox.message_id,
                Message.tenant_id == outbox.tenant_id,
            )
            .with_for_update()
        )
        if message is None:
            raise AccessDenied
        now = datetime.now(UTC)
        if outbox.status == "dispatching":
            if outbox.lease_until is not None and outbox.lease_until <= now:
                outbox.status = "uncertain"
                outbox.last_error = "dispatch_interrupted"
                message.status = "uncertain"
                message.processing_error = "dispatch_interrupted"
                outbox.lease_until = None
            return None
        if outbox.status not in {"pending", "retry"} or outbox.available_at > now:
            return None
        conversation = session.scalar(
            select(Conversation).where(
                Conversation.id == message.conversation_id,
                Conversation.tenant_id == message.tenant_id,
            )
        )
        if (
            conversation is None
            or conversation.last_inbound_at is None
            or conversation.last_inbound_at <= now - timedelta(hours=24)
        ):
            outbox.status = "blocked"
            message.status = "blocked"
            outbox.last_error = message.processing_error = "template_required"
            return None
        if outbox.attempts >= MAX_ATTEMPTS:
            outbox.status = "failed"
            message.status = "failed"
            outbox.last_error = message.processing_error = "retry_exhausted"
            return None
        outbox.status = "dispatching"
        outbox.attempts += 1
        outbox.dispatch_started_at = now
        outbox.lease_until = now + DISPATCH_LEASE
        outbox.last_error = None
        return SendCommand(
            job,
            "whatsapp:" + link.phone,
            message.body,
            callback_url(
                self.settings.twilio_status_url
                or "https://simulator.invalid/webhooks/twilio/status",
                outbox.id,
            ),
        )

    def _dispatch_allowed(self, command: SendCommand) -> bool:
        """Check the committed intent again immediately before provider I/O."""
        with Session(self.engine) as session, session.begin():
            self._check(session)
            authorise_route(session, command.job.route)
            outbox = session.scalar(
                select(Outbox)
                .where(
                    Outbox.id == command.job.entity_id,
                    Outbox.tenant_id == command.job.route.tenant_id,
                )
                .with_for_update()
            )
            if outbox is None or outbox.status != "dispatching":
                return False
            message = session.scalar(
                select(Message).where(
                    Message.id == outbox.message_id,
                    Message.tenant_id == outbox.tenant_id,
                )
            )
            if message is None:
                raise AccessDenied
            now = datetime.now(UTC)
            if outbox.lease_until is None or outbox.lease_until <= now:
                outbox.status = message.status = "uncertain"
                outbox.last_error = message.processing_error = "dispatch_interrupted"
                outbox.lease_until = None
                return False
            conversation = session.scalar(
                select(Conversation).where(
                    Conversation.id == message.conversation_id,
                    Conversation.tenant_id == message.tenant_id,
                )
            )
            if (
                conversation is None
                or conversation.last_inbound_at is None
                or conversation.last_inbound_at <= now - timedelta(hours=24)
            ):
                outbox.status = message.status = "blocked"
                outbox.last_error = message.processing_error = "template_required"
                outbox.lease_until = None
                return False
            return True

    def _send(self, command: SendCommand) -> None:
        if not self._dispatch_allowed(command):
            return
        outcome: SendResult | SafeRetry | PermanentFailure | AmbiguousFailure
        try:
            outcome = self.provider.send_text(
                to=command.to,
                body=command.body,
                callback_url=command.callback,
            )
        except (SafeRetry, PermanentFailure, AmbiguousFailure) as error:
            outcome = error
        except Exception:
            outcome = AmbiguousFailure("unexpected_provider_error")
        # If this transaction fails, dispatching remains durable. Recovery moves
        # it to uncertain; it cannot repeat the customer-visible provider call.
        with Session(self.engine) as session, session.begin():
            self._check(session)
            authorise_route(session, command.job.route)
            outbox = session.scalar(
                select(Outbox)
                .where(
                    Outbox.id == command.job.entity_id,
                    Outbox.tenant_id == command.job.route.tenant_id,
                )
                .with_for_update()
            )
            if outbox is None or outbox.status != "dispatching":
                return  # A callback may already have confirmed provider acceptance.
            message = session.scalar(
                select(Message)
                .where(
                    Message.id == outbox.message_id,
                    Message.tenant_id == outbox.tenant_id,
                )
                .with_for_update()
            )
            if message is None:
                raise AccessDenied
            outbox.lease_until = None
            if isinstance(outcome, SendResult):
                if message.twilio_sid is not None and message.twilio_sid != outcome.sid:
                    outbox.status = "uncertain"
                    outbox.last_error = "provider_sid_mismatch"
                else:
                    message.twilio_sid = outcome.sid
                    advance_status(message, outcome.status)
                    outbox.status = "sent"
                    outbox.last_error = None
            elif isinstance(outcome, SafeRetry):
                outbox.status = "retry" if outbox.attempts < MAX_ATTEMPTS else "failed"
                if outbox.status == "failed":
                    message.status = "failed"
                outbox.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(3600, outcome.retry_after * 2 ** (outbox.attempts - 1)),
                )
                outbox.last_error = "rate_limited"
                message.processing_error = "rate_limited"
            else:
                outbox.status = "failed" if isinstance(outcome, PermanentFailure) else "uncertain"
                message.status = outbox.status
                outbox.last_error = outcome.code
                message.processing_error = outcome.code


def main() -> None:
    parser = argparse.ArgumentParser(description="An Oifig durable text messaging worker")
    parser.add_argument("--once", action="store_true", help="process one discovery batch")
    parser.add_argument("--local", action="store_true", help="simulate delivery; no provider HTTP")
    args = parser.parse_args()
    settings = get_settings()
    provider: MessagingProvider
    if args.local:
        if settings.environment == "production":
            parser.error("local simulator is forbidden in production")
        provider = LocalMessagingProvider()
    else:
        if not settings.twilio_enabled:
            parser.error("enable and configure Twilio, or explicitly select --local")
        assert settings.twilio_account_sid and settings.twilio_auth_token
        assert settings.twilio_whatsapp_number
        provider = TwilioMessagingProvider(
            account_sid=settings.twilio_account_sid.get_secret_value(),
            auth_token=settings.twilio_auth_token.get_secret_value(),
            whatsapp_number=settings.twilio_whatsapp_number,
            timeout=settings.twilio_http_timeout,
        )
    engine = build_engine(settings)
    worker = MessagingWorker(engine, settings, provider)
    try:
        while True:
            try:
                count = worker.run_once()
            except SQLAlchemyError:
                logger.warning("Messaging discovery unavailable")
                count = 0
            if args.once:
                break
            if not count:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
