"""Initial entities; schema privileges and row policies live in migrations."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from anoifig.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Business(TimestampMixin, Base):
    __tablename__ = "businesses"
    __table_args__ = (CheckConstraint("btrim(legal_name) <> ''", name="legal_name_not_empty"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(35), nullable=False, server_default="en-IE")
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Europe/Dublin"
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "identity_provider_issuer",
            "identity_provider_subject",
            name="uq_users_identity",
        ),
        CheckConstraint("btrim(identity_provider_issuer) <> ''", name="identity_issuer_not_empty"),
        CheckConstraint(
            "btrim(identity_provider_subject) <> ''", name="identity_subject_not_empty"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    identity_provider_issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    identity_provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'staff', 'read_only')", name="valid_role"),
        Index("ix_memberships_user_id", "user_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
        CheckConstraint("btrim(name) <> ''", name="name_not_empty"),
        Index("ix_customers_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    billing_address: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    vat_number: Mapped[str | None] = mapped_column(String(32))
