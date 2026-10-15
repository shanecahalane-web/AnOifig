"""Work discovery and settlement contract for local and future broker adapters.

PostgreSQL is the durable acceptance boundary. A future Azure Service Bus adapter
must use a database pump to publish persisted work, renew broker locks as needed,
and complete a delivery only after its processing transaction commits. Broker
settlement cannot replace the domain handler's row locks and idempotency checks.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import Engine, text

from anoifig.config import Settings
from anoifig.db.session import check_runtime_database


@dataclass(frozen=True, slots=True)
class QueueDelivery:
    """Work identity plus an opaque adapter-specific settlement receipt."""

    id: UUID
    receipt: str


class WorkQueue(Protocol):
    def receive(self, limit: int = 100) -> list[QueueDelivery]:
        """Discover available work; handlers must tolerate repeated delivery."""
        ...

    def complete(self, delivery: QueueDelivery) -> None:
        """Settle a delivery only after the database transaction commits."""
        ...

    def abandon(self, delivery: QueueDelivery) -> None:
        """Release a failed delivery for retry; persisted retry rules still apply."""
        ...


class PostgresWorkQueue:
    """Claim durable work using opaque receipts and bounded metadata leases.

    Claims coordinate polling workers without granting tenant access. Domain
    handlers still lock and recheck source state within their transaction.
    Expired claims recover after a worker crash; settling an older receipt
    cannot release a newer worker's delivery. Least-recently-claimed ordering
    prevents busy source rows from starving later work.
    """

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    def receive(self, limit: int = 100) -> list[QueueDelivery]:
        if not 1 <= limit <= 1000:
            raise ValueError("queue receive limit must be between 1 and 1000")
        with self._engine.begin() as connection:
            check_runtime_database(
                connection, require_tls=self._settings.environment == "production"
            )
            deliveries = connection.execute(
                text("SELECT job_id, receipt FROM public.messaging_claim_jobs(:limit)"),
                {"limit": limit},
            )
            return [
                QueueDelivery(id=UUID(str(row.job_id)), receipt=str(row.receipt))
                for row in deliveries
            ]

    def complete(self, delivery: QueueDelivery) -> None:
        """Release this receipt after the domain transaction has committed."""
        self._release(delivery, delay=0)

    def abandon(self, delivery: QueueDelivery) -> None:
        """Release this receipt with a short cooldown for contended source rows."""
        self._release(delivery, delay=1)

    def _release(self, delivery: QueueDelivery, *, delay: int) -> None:
        with self._engine.begin() as connection:
            check_runtime_database(
                connection, require_tls=self._settings.environment == "production"
            )
            connection.execute(
                text("SELECT public.messaging_release_job(:job, :receipt, :delay)"),
                {"job": delivery.id, "receipt": UUID(delivery.receipt), "delay": delay},
            )
