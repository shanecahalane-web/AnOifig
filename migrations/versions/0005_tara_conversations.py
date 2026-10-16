"""Durable Tara notes, fenced processing and conservative business budgets.

Revision ID: 0005_tara_conversations
Revises: 0004_messaging_queue_fairness
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_tara_conversations"
down_revision: str | Sequence[str] | None = "0004_messaging_queue_fairness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE messages ADD CONSTRAINT uq_messages_tenant_id_id_conversation_user
            UNIQUE (tenant_id, id, conversation_id, user_id);
        CREATE INDEX ix_messages_pending_conversation ON messages
            (tenant_id, conversation_id, received_at, id)
            WHERE direction = 'inbound' AND processed_at IS NULL;
        CREATE TABLE tara_states (
            conversation_id UUID CONSTRAINT pk_tara_states PRIMARY KEY,
            tenant_id UUID NOT NULL,
            user_id UUID NOT NULL,
            notes JSONB NOT NULL DEFAULT '{}'::jsonb,
            version INTEGER NOT NULL DEFAULT 0
                CONSTRAINT ck_tara_states_valid_version CHECK (version >= 0),
            memory_since TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_tara_states_object_notes CHECK (jsonb_typeof(notes) = 'object'),
            CONSTRAINT fk_tara_states_tenant_id_conversations
                FOREIGN KEY (tenant_id, conversation_id, user_id)
                REFERENCES conversations (tenant_id, id, user_id) ON DELETE CASCADE
        );
        CREATE INDEX ix_tara_states_tenant_id ON tara_states (tenant_id);
        CREATE TABLE tara_runs (
            message_id UUID CONSTRAINT pk_tara_runs PRIMARY KEY,
            tenant_id UUID NOT NULL,
            conversation_id UUID NOT NULL,
            user_id UUID NOT NULL,
            token UUID NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            status VARCHAR(16) NOT NULL
                CONSTRAINT ck_tara_runs_valid_status CHECK (status IN ('processing', 'complete')),
            model VARCHAR(100) NOT NULL,
            prompt_version VARCHAR(64) NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            usage_day DATE NOT NULL,
            reserved_tokens INTEGER NOT NULL,
            reserved_cost NUMERIC(18,8) NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            estimated_cost NUMERIC(18,8),
            error_code VARCHAR(64),
            intent VARCHAR(32),
            action VARCHAR(32),
            CONSTRAINT ck_tara_runs_valid_reservation
                CHECK (reserved_tokens >= 0 AND reserved_cost >= 0),
            CONSTRAINT ck_tara_runs_valid_usage CHECK (input_tokens >= 0 AND output_tokens >= 0),
            CONSTRAINT fk_tara_runs_tenant_id_messages
                FOREIGN KEY (tenant_id, message_id, conversation_id, user_id)
                REFERENCES messages (tenant_id, id, conversation_id, user_id) ON DELETE CASCADE
        );
        CREATE INDEX ix_tara_runs_tenant_id ON tara_runs (tenant_id);
        CREATE TABLE tara_usage (
            tenant_id UUID NOT NULL CONSTRAINT fk_tara_usage_tenant_id_businesses
                REFERENCES businesses (id) ON DELETE CASCADE,
            day DATE NOT NULL,
            requests INTEGER NOT NULL DEFAULT 0,
            tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd NUMERIC(18,8) NOT NULL DEFAULT 0,
            CONSTRAINT pk_tara_usage PRIMARY KEY (tenant_id, day),
            CONSTRAINT ck_tara_usage_valid_usage
                CHECK (requests >= 0 AND tokens >= 0 AND cost_usd >= 0)
        );
    """)
    for table in ("tara_states", "tara_runs", "tara_usage"):
        member = f"""
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            AND EXISTS (SELECT 1 FROM public.businesses b WHERE b.id = {table}.tenant_id)
            AND EXISTS (SELECT 1 FROM public.memberships m
                WHERE m.tenant_id = {table}.tenant_id AND m.role IN ('owner', 'staff'))
        """
        if table != "tara_usage":
            member += f"""
                AND EXISTS (SELECT 1 FROM public.conversations c
                    WHERE c.tenant_id = {table}.tenant_id
                    AND c.id = {table}.conversation_id AND c.user_id = {table}.user_id)
            """
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        op.execute(f"CREATE POLICY {table}_read_member ON {table} FOR SELECT USING ({member})")
        op.execute(
            f"CREATE POLICY {table}_insert_writer ON {table} FOR INSERT WITH CHECK ({member})"
        )
        op.execute(
            f"CREATE POLICY {table}_update_writer ON {table} "
            f"FOR UPDATE USING ({member}) WITH CHECK ({member})"
        )


def downgrade() -> None:
    for table in ("tara_usage", "tara_runs", "tara_states"):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP INDEX ix_messages_pending_conversation")
    op.execute("ALTER TABLE messages DROP CONSTRAINT uq_messages_tenant_id_id_conversation_user")
