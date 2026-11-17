"""Persist version-bound, user-confirmed preparation-note proposals.

Revision ID: 0007_tara_pending_proposals
Revises: 0006_tara_turn_boundaries
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_tara_pending_proposals"
down_revision: str | Sequence[str] | None = "0006_tara_turn_boundaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tara_pending_proposals (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            user_id UUID NOT NULL,
            conversation_id UUID NOT NULL,
            source_message_id UUID NOT NULL UNIQUE,
            confirmation_message_id UUID UNIQUE,
            expected_version INTEGER NOT NULL CHECK (expected_version >= 0),
            before_notes JSONB NOT NULL CHECK (jsonb_typeof(before_notes) = 'object'),
            after_notes JSONB NOT NULL CHECK (jsonb_typeof(after_notes) = 'object'),
            challenge VARCHAR(32) NOT NULL UNIQUE CHECK (challenge ~ '^[0-9A-F]{32}$'),
            status VARCHAR(16) NOT NULL CHECK (status IN
                ('pending', 'confirmed', 'rejected', 'expired', 'superseded')),
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT fk_proposal_source FOREIGN KEY
                (tenant_id, source_message_id, conversation_id, user_id)
                REFERENCES messages (tenant_id, id, conversation_id, user_id),
            CONSTRAINT fk_proposal_confirmation FOREIGN KEY
                (tenant_id, confirmation_message_id, conversation_id, user_id)
                REFERENCES messages (tenant_id, id, conversation_id, user_id),
            CONSTRAINT fk_proposal_conversation FOREIGN KEY (tenant_id, conversation_id, user_id)
                REFERENCES conversations (tenant_id, id, user_id),
            CHECK (expires_at > created_at)
        );
        CREATE UNIQUE INDEX uq_tara_pending_per_conversation
            ON tara_pending_proposals (tenant_id, conversation_id) WHERE status = 'pending';
        CREATE INDEX ix_tara_pending_proposals_tenant_id ON tara_pending_proposals (tenant_id);
        ALTER TABLE tara_pending_proposals ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tara_pending_proposals FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON tara_pending_proposals FROM PUBLIC;
    """)
    member = """
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        AND EXISTS (SELECT 1 FROM public.businesses b WHERE b.id = tara_pending_proposals.tenant_id)
        AND EXISTS (SELECT 1 FROM public.memberships m
                    WHERE m.tenant_id = tara_pending_proposals.tenant_id
                      AND m.role IN ('owner', 'staff'))
        AND EXISTS (SELECT 1 FROM public.conversations c
                    WHERE c.tenant_id = tara_pending_proposals.tenant_id
                      AND c.id = tara_pending_proposals.conversation_id
                      AND c.user_id = tara_pending_proposals.user_id)
    """
    op.execute(
        "CREATE POLICY tara_pending_proposals_read_member ON tara_pending_proposals "
        f"FOR SELECT USING ({member})"
    )
    op.execute(
        "CREATE POLICY tara_pending_proposals_insert_writer ON tara_pending_proposals "
        f"FOR INSERT WITH CHECK ({member})"
    )
    op.execute(
        "CREATE POLICY tara_pending_proposals_update_writer ON tara_pending_proposals "
        f"FOR UPDATE USING ({member}) WITH CHECK ({member})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE tara_pending_proposals")
