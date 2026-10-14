"""Create identity, membership and customer tables with forced row isolation.

Revision ID: 0001_initial_foundation
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_foundation"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "businesses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("trading_name", sa.String(255), nullable=True),
        sa.Column("locale", sa.String(35), nullable=False, server_default="en-IE"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Dublin"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_businesses")),
        sa.CheckConstraint(
            "btrim(legal_name) <> ''", name=op.f("ck_businesses_legal_name_not_empty")
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_provider_issuer", sa.String(512), nullable=False),
        sa.Column("identity_provider_subject", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint(
            "identity_provider_issuer",
            "identity_provider_subject",
            name="uq_users_identity",
        ),
        sa.CheckConstraint(
            "btrim(identity_provider_issuer) <> ''",
            name=op.f("ck_users_identity_issuer_not_empty"),
        ),
        sa.CheckConstraint(
            "btrim(identity_provider_subject) <> ''",
            name=op.f("ck_users_identity_subject_not_empty"),
        ),
    )
    op.create_table(
        "memberships",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name=op.f("pk_memberships")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["businesses.id"], name=op.f("fk_memberships_tenant_id_businesses")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users")
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'staff', 'read_only')",
            name=op.f("ck_memberships_valid_role"),
        ),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("billing_address", sa.Text(), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("vat_number", sa.String(32), nullable=True),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["businesses.id"], name=op.f("fk_customers_tenant_id_businesses")
        ),
        # Future relationships must reference this pair, not a customer's id alone.
        sa.UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_customers_name_not_empty")),
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])

    # Database-managed modification timestamps also apply to raw SQL writes.
    op.execute(
        """
        CREATE FUNCTION public.touch_updated_at() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            NEW.updated_at = statement_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    for table in ("businesses", "users", "memberships", "customers"):
        op.execute(
            f"CREATE TRIGGER touch_updated_at BEFORE UPDATE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at()"
        )
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")

    # The application sets these settings transaction-locally *after* JWT verification.
    # No SECURITY DEFINER helper bypasses RLS; policy dependencies are acyclic:
    # customers -> businesses -> memberships -> users.
    op.execute(
        """
        CREATE POLICY users_read_self ON public.users FOR SELECT USING (
            active
            AND identity_provider_issuer = NULLIF(current_setting('app.issuer', true), '')
            AND identity_provider_subject = NULLIF(current_setting('app.subject', true), '')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY memberships_read_self ON public.memberships FOR SELECT USING (
            active AND EXISTS (
                SELECT 1 FROM public.users
                WHERE users.id = memberships.user_id
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY businesses_read_member ON public.businesses FOR SELECT USING (
            active AND EXISTS (
                SELECT 1 FROM public.memberships
                WHERE memberships.tenant_id = businesses.id
            )
        )
        """
    )
    authorised_customer = """
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM public.businesses WHERE businesses.id = customers.tenant_id
        )
    """
    writable_customer = (
        authorised_customer
        + """
        AND EXISTS (
            SELECT 1 FROM public.memberships
            WHERE memberships.tenant_id = customers.tenant_id
              AND memberships.role IN ('owner', 'staff')
        )
    """
    )
    op.execute(
        "CREATE POLICY customers_read_member ON public.customers FOR SELECT "
        f"USING ({authorised_customer})"
    )
    op.execute(
        "CREATE POLICY customers_insert_writer ON public.customers FOR INSERT "
        f"WITH CHECK ({writable_customer})"
    )
    op.execute(
        "CREATE POLICY customers_update_writer ON public.customers FOR UPDATE "
        f"USING ({writable_customer}) WITH CHECK ({writable_customer})"
    )
    op.execute(
        "CREATE POLICY customers_delete_writer ON public.customers FOR DELETE "
        f"USING ({writable_customer})"
    )


def downgrade() -> None:
    # Remove cross-table policy dependencies before dropping their target tables.
    for policy in (
        "customers_read_member",
        "customers_insert_writer",
        "customers_update_writer",
        "customers_delete_writer",
    ):
        op.execute(f"DROP POLICY {policy} ON public.customers")
    op.execute("DROP POLICY businesses_read_member ON public.businesses")
    op.execute("DROP POLICY memberships_read_self ON public.memberships")
    op.execute("DROP POLICY users_read_self ON public.users")
    # Triggers and indexes are removed with their tables.
    op.drop_table("customers")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("businesses")
    op.execute("DROP FUNCTION public.touch_updated_at()")
