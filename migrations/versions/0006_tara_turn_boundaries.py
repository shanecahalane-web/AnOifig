"""Add application-owned turn boundaries and correction versions without rewriting data.

Revision ID: 0006_tara_turn_boundaries
Revises: 0005_tara_conversations
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_tara_turn_boundaries"
down_revision: str | Sequence[str] | None = "0005_tara_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE tara_states ADD COLUMN memory_after_id UUID,
            ADD COLUMN pending_clarification VARCHAR(16),
            ADD CONSTRAINT ck_tara_states_valid_clarification
                CHECK (pending_clarification IN ('vat_basis', 'vat_rate'));
        ALTER TABLE tara_runs ADD COLUMN expected_version INTEGER,
            ADD CONSTRAINT ck_tara_runs_valid_expected_version CHECK (expected_version >= 0);
        ALTER TABLE messages ADD COLUMN conversation_version INTEGER,
            ADD CONSTRAINT ck_messages_valid_conversation_version
                CHECK (conversation_version >= 0);
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE messages DROP COLUMN conversation_version;
        ALTER TABLE tara_runs DROP COLUMN expected_version;
        ALTER TABLE tara_states DROP COLUMN pending_clarification,
            DROP COLUMN memory_after_id;
    """)
