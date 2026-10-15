"""Tenant messaging records and minimal cross-tenant routing metadata.

Only the reviewed gateway functions may read routing metadata without an
authenticated identity. Conversations and message content always remain under
the ordinary tenant/identity row policies.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from anoifig.db.base import Base
from anoifig.db.models import TimestampMixin


class PhoneLink(TimestampMixin, Base):
    __tablename__ = "phone_links"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_phone_links_tenant_id_id"),
        UniqueConstraint("tenant_id", "id", "user_id", name="uq_phone_links_tenant_id_id_user"),
        UniqueConstraint("token_hash", name="uq_phone_links_token_hash"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["memberships.tenant_id", "memberships.user_id"]
        ),
        CheckConstraint("phone ~ '^\\+[1-9][0-9]{6,14}$'", name="valid_phone"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="valid_token_hash"),
        Index(
            "uq_phone_links_verified_phone",
            "phone",
            unique=True,
            postgresql_where=text("verified_at IS NOT NULL AND revoked_at IS NULL"),
        ),
        Index("ix_phone_links_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id_id"),
        UniqueConstraint("tenant_id", "id", "user_id", name="uq_conversations_tenant_id_id_user"),
        UniqueConstraint(
            "tenant_id",
            "id",
            "phone_link_id",
            "user_id",
            name="uq_conversations_tenant_id_id_link_user",
        ),
        UniqueConstraint("tenant_id", "phone_link_id", name="uq_conversations_tenant_link"),
        ForeignKeyConstraint(
            ["tenant_id", "phone_link_id", "user_id"],
            ["phone_links.tenant_id", "phone_links.id", "phone_links.user_id"],
        ),
        Index("ix_conversations_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    phone_link_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_messages_tenant_id_id"),
        UniqueConstraint("tenant_id", "id", "phone_link_id", name="uq_messages_tenant_id_id_link"),
        UniqueConstraint("twilio_sid", name="uq_messages_twilio_sid"),
        UniqueConstraint("reply_to_id", name="uq_messages_reply_to_id"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "phone_link_id", "user_id"],
            [
                "conversations.tenant_id",
                "conversations.id",
                "conversations.phone_link_id",
                "conversations.user_id",
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "reply_to_id"], ["messages.tenant_id", "messages.id"]),
        CheckConstraint("direction IN ('inbound', 'outbound')", name="valid_direction"),
        CheckConstraint("length(body) BETWEEN 1 AND 4096", name="valid_body"),
        CheckConstraint(
            "twilio_sid IS NULL OR twilio_sid ~ '^(SM|MM)[0-9a-fA-F]{32}$'", name="valid_twilio_sid"
        ),
        CheckConstraint("account_sid ~ '^AC[0-9a-fA-F]{32}$'", name="valid_account_sid"),
        CheckConstraint("reply_to_id IS NULL OR direction = 'outbound'", name="valid_reply"),
        CheckConstraint("processing_attempts >= 0", name="nonnegative_processing_attempts"),
        Index("ix_messages_tenant_conversation", "tenant_id", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    phone_link_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    twilio_sid: Mapped[str | None] = mapped_column(String(34))
    account_sid: Mapped[str] = mapped_column(String(34), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="received")
    processing_error: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_to_id: Mapped[UUID | None] = mapped_column()
    processing_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Outbox(TimestampMixin, Base):
    __tablename__ = "outbox"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_outbox_tenant_id_id"),
        UniqueConstraint("message_id", name="uq_outbox_message_id"),
        ForeignKeyConstraint(
            ["tenant_id", "message_id", "phone_link_id"],
            ["messages.tenant_id", "messages.id", "messages.phone_link_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "phone_link_id"], ["phone_links.tenant_id", "phone_links.id"]
        ),
        CheckConstraint(
            "status IN ('pending', 'dispatching', 'retry', 'sent', "
            "'uncertain', 'failed', 'blocked')",
            name="valid_status",
        ),
        CheckConstraint("attempts >= 0", name="nonnegative_attempts"),
        Index("ix_outbox_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    message_id: Mapped[UUID] = mapped_column(nullable=False)
    phone_link_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(64))


class MessageJob(Base):
    """Content-free gateway index maintained exclusively by source-table triggers."""

    __tablename__ = "message_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "phone_link_id"],
            ["phone_links.tenant_id", "phone_links.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "message_id"], ["messages.tenant_id", "messages.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "outbox_id"], ["outbox.tenant_id", "outbox.id"], ondelete="CASCADE"
        ),
        CheckConstraint("kind IN ('inbound', 'outbound')", name="valid_kind"),
        CheckConstraint("id = entity_id", name="entity_identity"),
        CheckConstraint(
            "(kind = 'inbound' AND message_id = entity_id AND outbox_id IS NULL) "
            "OR (kind = 'outbound' AND outbox_id = entity_id AND message_id IS NULL)",
            name="valid_entity",
        ),
        Index("ix_message_jobs_ready_due", "ready", "due_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    phone_link_id: Mapped[UUID] = mapped_column(nullable=False)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[UUID | None] = mapped_column()
    outbox_id: Mapped[UUID | None] = mapped_column()
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(64))
