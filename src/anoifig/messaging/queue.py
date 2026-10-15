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
    """Discover durable ready/due work without a paid broker or in-memory state.

    Discovery grants no claim or tenant access: only opaque job IDs leave this
    adapter. Concurrent workers can discover the same ID, so the domain handler
    must lock and recheck the row within its processing transaction. Completing
    or abandoning a local delivery needs no separate write: committed domain
    state determines whether and when PostgreSQL discovers the work again.
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
            job_ids = connection.execute(
                text("SELECT job_id FROM public.messaging_discover_jobs(:limit)"),
                {"limit": limit},
            ).scalars()
            return [QueueDelivery(id=UUID(str(job_id)), receipt=str(job_id)) for job_id in job_ids]

    def complete(self, delivery: QueueDelivery) -> None:
        """Committed domain state already removes or reschedules local work."""

    def abandon(self, delivery: QueueDelivery) -> None:
        """Uncommitted work remains durable and discoverable for another worker."""
