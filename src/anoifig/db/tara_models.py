"""Application-owned notes, processing fences, audit metadata and usage budgets."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from anoifig.db.base import Base


class TaraState(Base):
    __tablename__ = "tara_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "user_id"],
            ["conversations.tenant_id", "conversations.id", "conversations.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("version >= 0", name="valid_version"),
        CheckConstraint("jsonb_typeof(notes) = 'object'", name="object_notes"),
    )
    conversation_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    notes: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    memory_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaraRun(Base):
    __tablename__ = "tara_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "message_id", "conversation_id", "user_id"],
            ["messages.tenant_id", "messages.id", "messages.conversation_id", "messages.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("status IN ('processing', 'complete')", name="valid_status"),
        CheckConstraint("reserved_tokens >= 0 AND reserved_cost >= 0", name="valid_reservation"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="valid_usage"),
    )
    message_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    token: Mapped[UUID] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage_day: Mapped[date] = mapped_column(Date, nullable=False)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    error_code: Mapped[str | None] = mapped_column(String(64))
    intent: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str | None] = mapped_column(String(32))


class TaraUsage(Base):
    __tablename__ = "tara_usage"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["businesses.id"], ondelete="CASCADE"),
        CheckConstraint("requests >= 0 AND tokens >= 0 AND cost_usd >= 0", name="valid_usage"),
    )
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default="0")
