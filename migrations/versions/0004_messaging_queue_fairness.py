"""Give new and previously attempted jobs the same age-based queue turns.

Revision ID: 0004_messaging_queue_fairness
Revises: 0003_messaging_queue_claims

Keep applied revision 0003 intact. Replacing the two scheduling functions keeps
their signatures, owners and ACLs; source data, claims and RLS are unchanged.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_messaging_queue_fairness"
down_revision: str | Sequence[str] | None = "0003_messaging_queue_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_scheduling_functions(*, fair: bool) -> None:
    # A fresh job joins at due_at. Each claim moves its turn to at least the
    # statement clock; a later business retry due time moves it later still.
    # There is no permanent priority class, per-tenant state, or worker counter.
    turn = (
        "GREATEST(j.due_at, COALESCE(j.last_claimed_at, j.due_at))" if fair else "j.last_claimed_at"
    )
    nulls = "" if fair else " NULLS FIRST"
    # Bound the expression-index scan before future turns. Claims always use
    # the database statement clock, so ready/due work has no future claim time.
    available_turn = f"AND {turn} <= statement_timestamp()" if fair else ""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.messaging_discover_jobs(batch_size integer DEFAULT 100)
        RETURNS TABLE(job_id uuid, kind text, entity_id uuid, tenant_id uuid,
                      link_id uuid, issuer text, subject text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT j.id, j.kind::text, j.entity_id, j.tenant_id,
                   j.phone_link_id, j.issuer::text, j.subject::text
              FROM public.message_jobs j
             WHERE j.ready AND j.due_at <= statement_timestamp()
               AND (j.claim_until IS NULL OR j.claim_until <= statement_timestamp())
               {available_turn}
             ORDER BY {turn}{nulls}, j.due_at, j.id
             LIMIT LEAST(GREATEST(COALESCE(batch_size, 100), 1), 1000)
        $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.messaging_claim_jobs(batch_size integer DEFAULT 100)
        RETURNS TABLE(job_id uuid, receipt uuid)
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
            WITH candidates AS MATERIALIZED (
                SELECT j.id, {turn} AS turn_at, j.due_at
                  FROM public.message_jobs j
                 WHERE j.ready AND j.due_at <= statement_timestamp()
                   AND (j.claim_until IS NULL OR j.claim_until <= statement_timestamp())
                   {available_turn}
                 ORDER BY {turn}{nulls}, j.due_at, j.id
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
             ORDER BY selected.turn_at{nulls}, selected.due_at, selected.id
        $$
        """
    )


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_message_jobs_ready_turn ON public.message_jobs "
        "(GREATEST(due_at, COALESCE(last_claimed_at, due_at)), due_at, id) WHERE ready"
    )
    _replace_scheduling_functions(fair=True)
    op.execute("DROP INDEX public.ix_message_jobs_ready_claimed_due")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX ix_message_jobs_ready_claimed_due ON public.message_jobs "
        "(ready, last_claimed_at, due_at, id)"
    )
    _replace_scheduling_functions(fair=False)
    op.execute("DROP INDEX public.ix_message_jobs_ready_turn")
