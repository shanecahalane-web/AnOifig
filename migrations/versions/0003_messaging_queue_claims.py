"""Fair, receipt-bound operational claims on the content-free message queue.

Revision ID: 0003_messaging_queue_claims
Revises: 0002_whatsapp_messaging

Applied messaging schemas upgrade in place. Source triggers update only their
existing scheduling columns, preserving claims while domain state changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_messaging_queue_claims"
down_revision: str | Sequence[str] | None = "0002_whatsapp_messaging"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.message_jobs
            ADD COLUMN claim_token uuid,
            ADD COLUMN claim_until timestamp with time zone,
            ADD COLUMN last_claimed_at timestamp with time zone
        """
    )
    op.execute(
        "CREATE INDEX ix_message_jobs_ready_claimed_due ON public.message_jobs "
        "(ready, last_claimed_at, due_at, id)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.messaging_discover_jobs(batch_size integer DEFAULT 100)
        RETURNS TABLE(job_id uuid, kind text, entity_id uuid, tenant_id uuid,
                      link_id uuid, issuer text, subject text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT j.id, j.kind::text, j.entity_id, j.tenant_id,
                   j.phone_link_id, j.issuer::text, j.subject::text
              FROM public.message_jobs j
             WHERE j.ready AND j.due_at <= statement_timestamp()
               AND (j.claim_until IS NULL OR j.claim_until <= statement_timestamp())
             ORDER BY j.last_claimed_at NULLS FIRST, j.due_at, j.id
             LIMIT LEAST(GREATEST(COALESCE(batch_size, 100), 1), 1000)
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.messaging_claim_jobs(batch_size integer DEFAULT 100)
        RETURNS TABLE(job_id uuid, receipt uuid)
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
            WITH candidates AS MATERIALIZED (
                SELECT j.id, j.last_claimed_at, j.due_at
                  FROM public.message_jobs j
                 WHERE j.ready AND j.due_at <= statement_timestamp()
                   AND (j.claim_until IS NULL OR j.claim_until <= statement_timestamp())
                 ORDER BY j.last_claimed_at NULLS FIRST, j.due_at, j.id
                 LIMIT LEAST(GREATEST(COALESCE(batch_size, 100), 1), 1000)
                 FOR UPDATE OF j SKIP LOCKED
            ), claimed AS (
                UPDATE public.message_jobs j
                   SET claim_token = gen_random_uuid(),
                       claim_until = statement_timestamp() + interval '120 seconds',
                       last_claimed_at = statement_timestamp()
                  FROM candidates c WHERE j.id = c.id
                RETURNING j.id, j.claim_token
            )
            SELECT c.id, c.claim_token FROM claimed c
              JOIN candidates selected ON selected.id = c.id
             ORDER BY selected.last_claimed_at NULLS FIRST, selected.due_at, selected.id
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.messaging_release_job(
            job_value uuid, receipt_value uuid, delay_seconds integer)
        RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
            UPDATE public.message_jobs j
               SET claim_token = NULL,
                   claim_until = CASE WHEN delay_seconds = 1
                                      THEN statement_timestamp() + interval '1 second'
                                      ELSE NULL END
             WHERE j.id = job_value AND j.claim_token = receipt_value
               AND delay_seconds IN (0, 1)
        $$
        """
    )
    for function in (
        "messaging_discover_jobs(integer)",
        "messaging_claim_jobs(integer)",
        "messaging_release_job(uuid,uuid,integer)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.messaging_release_job(uuid,uuid,integer)")
    op.execute("DROP FUNCTION public.messaging_claim_jobs(integer)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.messaging_discover_jobs(batch_size integer DEFAULT 100)
        RETURNS TABLE(job_id uuid, kind text, entity_id uuid, tenant_id uuid,
                      link_id uuid, issuer text, subject text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT j.id, j.kind::text, j.entity_id, j.tenant_id,
                   j.phone_link_id, j.issuer::text, j.subject::text
              FROM public.message_jobs j
             WHERE j.ready AND j.due_at <= statement_timestamp()
             ORDER BY j.due_at, j.id
             LIMIT LEAST(GREATEST(COALESCE(batch_size, 100), 1), 1000)
        $$
        """
    )
    op.execute("DROP INDEX public.ix_message_jobs_ready_claimed_due")
    op.execute(
        """
        ALTER TABLE public.message_jobs
            DROP COLUMN last_claimed_at,
            DROP COLUMN claim_until,
            DROP COLUMN claim_token
        """
    )
