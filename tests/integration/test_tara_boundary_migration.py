"""Revision 0006 preserves applied Tara/messaging data and their security contract."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from test_messaging import set_context
from test_messaging_claim_migration import insert_revision_0002_records

from anoifig.db.privileges import provision_runtime_grants
from anoifig.db.session import check_runtime_database

pytestmark = pytest.mark.integration
PREVIOUS = "0005_tara_conversations"
CURRENT = "0006_tara_turn_boundaries"
TABLE_ORDER = {
    "phone_links": "id",
    "conversations": "id",
    "messages": "id",
    "outbox": "id",
    "message_jobs": "id",
    "tara_states": "conversation_id",
    "tara_runs": "message_id",
    "tara_usage": "tenant_id, day",
}
NEW_COLUMNS = {
    "messages": {"conversation_version"},
    "tara_states": {"memory_after_id", "pending_clarification"},
    "tara_runs": {"expected_version"},
}


def durable_snapshot(database):
    """Compare every existing column, including queue receipts and usage charges."""
    with database.admin.connect() as connection:
        return {
            table: [
                {key: value for key, value in row.items() if key not in NEW_COLUMNS.get(table, ())}
                for row in connection.execute(
                    text(f"SELECT * FROM {table} ORDER BY {order}")
                ).mappings()
            ]
            for table, order in TABLE_ORDER.items()
        }


def security_snapshot(database):
    with database.admin.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT relname,relowner,relrowsecurity,relforcerowsecurity,relacl::text "
                    "FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                    "AND relkind = 'r' ORDER BY relname"
                )
            ).all(),
            connection.execute(
                text(
                    "SELECT tablename,policyname,permissive,roles,cmd,qual,with_check "
                    "FROM pg_policies WHERE schemaname = 'public' ORDER BY tablename,policyname"
                )
            ).all(),
            connection.execute(
                text(
                    "SELECT oid,proname,proowner,proacl::text,prosecdef,proconfig,provolatile "
                    "FROM pg_proc WHERE pronamespace = 'public'::regnamespace ORDER BY oid"
                )
            ).all(),
        )


def insert_revision_0005_tara_records(database, seed):
    """Raw SQL deliberately uses only the schema available to deployed revision 0005."""
    now = datetime.now(UTC)
    with database.admin.begin() as connection:
        messages = (
            connection.execute(
                text("SELECT * FROM messages WHERE direction = 'inbound' ORDER BY processed_at")
            )
            .mappings()
            .all()
        )
        assert len(messages) == 2
        processed = next(row for row in messages if row["processed_at"] is not None)
        pending = next(row for row in messages if row["processed_at"] is None)
        common = {
            "tenant": seed.businesses["a"],
            "user": seed.users["owner-a"],
            "conversation": processed["conversation_id"],
            "now": now,
            "day": now.date(),
        }
        connection.execute(
            text(
                "INSERT INTO tara_states "
                "(tenant_id,conversation_id,user_id,notes,version,memory_since,updated_at) "
                "VALUES (:tenant,:conversation,:user,CAST(:notes AS jsonb),4,:now,:now)"
            ),
            {
                **common,
                "notes": json.dumps(
                    {
                        "customer_name": "Synthetic migration customer",
                        "amount": "450",
                        "vat_basis": "unknown",
                        "line_items": [
                            {"description": "Valves", "quantity": "3", "unit_price": "25"}
                        ],
                    }
                ),
            },
        )
        for message, status in ((processed, "complete"), (pending, "processing")):
            complete = status == "complete"
            connection.execute(
                text(
                    "INSERT INTO tara_runs (message_id,tenant_id,conversation_id,user_id,token,"
                    "expires_at,status,model,prompt_version,started_at,completed_at,usage_day,"
                    "reserved_tokens,reserved_cost,input_tokens,output_tokens,estimated_cost,"
                    "error_code,intent,action) VALUES (:message,:tenant,:conversation,:user,:token,"
                    ":expires,:status,'offline-migration-model','migration-prompt',:now,:completed,"
                    ":day,12000,0.05,:input,:output,:cost,NULL,:intent,:action)"
                ),
                {
                    **common,
                    "message": message["id"],
                    "token": uuid4(),
                    "expires": now + timedelta(minutes=2),
                    "status": status,
                    "completed": now if complete else None,
                    "input": 100 if complete else None,
                    "output": 20 if complete else None,
                    "cost": "0.00018" if complete else None,
                    "intent": "invoice_preparation" if complete else None,
                    "action": "save_notes" if complete else None,
                },
            )
        connection.execute(
            text(
                "INSERT INTO tara_usage (tenant_id,day,requests,tokens,cost_usd) "
                "VALUES (:tenant,:day,3,24000,0.10)"
            ),
            common,
        )
    return pending["id"]


def assert_runtime_boundaries(database, seed):
    with database.runtime.begin() as connection:
        check_runtime_database(connection)
        assert connection.scalar(text("SELECT count(*) FROM tara_states")) == 0
        set_context(connection, seed)
        assert connection.scalar(text("SELECT count(*) FROM tara_states")) == 1
        assert connection.scalar(text("SELECT count(*) FROM tara_runs")) == 2
        assert connection.scalar(text("SELECT count(*) FROM tara_usage")) == 1
        set_context(connection, seed, tenant="b", subject="owner-b")
        assert connection.scalar(text("SELECT count(*) FROM tara_states")) == 0
        assert connection.scalar(text("SELECT count(*) FROM tara_runs")) == 0
        assert connection.scalar(text("SELECT count(*) FROM tara_usage")) == 0


def assert_new_columns_null(database):
    with database.admin.connect() as connection:
        for table, columns in NEW_COLUMNS.items():
            for column in columns:
                info = connection.execute(
                    text(
                        "SELECT is_nullable,column_default FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name=:table AND column_name=:column"
                    ),
                    {"table": table, "column": column},
                ).one()
                assert info == ("YES", None)
                assert (
                    connection.scalar(
                        text(f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL")
                    )
                    == 0
                )


def test_upgrade_downgrade_reupgrade_preserve_0005_records_security_and_grants(database, seed):
    config = Config("alembic.ini")
    role = make_url(database.runtime_url).username
    with patch.dict("os.environ", {"ANOIFIG_MIGRATION_DATABASE_URL": database.admin_url}):
        try:
            # Seed messaging with the current mapping, then leave real deployed
            # 0005 rows in place before inserting its notes/runs/usage through SQL.
            insert_revision_0002_records(database, seed)
            command.downgrade(config, PREVIOUS)
            pending_id = insert_revision_0005_tara_records(database, seed)
            with database.runtime.begin() as connection:
                assert connection.execute(text("SELECT * FROM messaging_claim_jobs(1)")).one()
            before = durable_snapshot(database)
            security = security_snapshot(database)
            assert len(before["messages"]) == 3 and len(before["message_jobs"]) == 3
            assert len(before["tara_runs"]) == 2 and before["tara_usage"][0]["requests"] == 3

            command.upgrade(config, CURRENT)
            assert durable_snapshot(database) == before
            assert security_snapshot(database) == security
            assert_new_columns_null(database)
            assert_runtime_boundaries(database, seed)
            command.check(config)

            # New application metadata is the only intended loss on downgrade.
            # Snapshot after these writes so trigger-managed timestamps are also
            # compared exactly through the subsequent schema-only operations.
            with database.admin.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE tara_states SET memory_after_id=:id,"
                        "pending_clarification='vat_basis'"
                    ),
                    {"id": pending_id},
                )
                connection.execute(text("UPDATE tara_runs SET expected_version=4"))
                connection.execute(text("UPDATE messages SET conversation_version=4"))
                for invalid_sql in (
                    "UPDATE tara_runs SET expected_version=-1",
                    "UPDATE messages SET conversation_version=-1",
                    "UPDATE tara_states SET pending_clarification='bank_transfer'",
                ):
                    with pytest.raises(IntegrityError), connection.begin_nested():
                        connection.execute(text(invalid_sql))
            after_metadata = durable_snapshot(database)
            command.downgrade(config, PREVIOUS)
            assert durable_snapshot(database) == after_metadata
            assert security_snapshot(database) == security
            assert_runtime_boundaries(database, seed)
            with database.admin.connect() as connection:
                for table, columns in NEW_COLUMNS.items():
                    existing = set(
                        connection.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_schema='public' AND table_name=:table"
                            ),
                            {"table": table},
                        ).scalars()
                    )
                    assert existing.isdisjoint(columns)

            command.upgrade(config, CURRENT)
            assert durable_snapshot(database) == after_metadata
            assert security_snapshot(database) == security
            assert_new_columns_null(database)
            assert_runtime_boundaries(database, seed)
            command.check(config)
        finally:
            command.upgrade(config, "head")
            with database.admin.begin() as connection:
                provision_runtime_grants(connection, role)
