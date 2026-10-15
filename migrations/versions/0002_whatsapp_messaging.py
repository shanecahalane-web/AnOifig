"""Durable WhatsApp records, tenant isolation and narrow routing gateways.

Revision ID: 0002_whatsapp_messaging
Revises: 0001_initial_foundation

Frozen PostgreSQL DDL is intentional: later model edits cannot change migration
history. Gateway owners have an explicit policy only on content-free routing
metadata, so this works with non-superuser schema owners under FORCE RLS.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_whatsapp_messaging"
down_revision: str | Sequence[str] | None = "0001_initial_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE phone_links (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            user_id UUID NOT NULL,
            phone VARCHAR(32) NOT NULL,
            issuer VARCHAR(512) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            token_hash VARCHAR(64),
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            verified_at TIMESTAMP WITH TIME ZONE,
            revoked_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_phone_links PRIMARY KEY (id),
            CONSTRAINT uq_phone_links_tenant_id_id UNIQUE (tenant_id, id),
            CONSTRAINT uq_phone_links_tenant_id_id_user UNIQUE (tenant_id, id, user_id),
            CONSTRAINT uq_phone_links_token_hash UNIQUE (token_hash),
            CONSTRAINT fk_phone_links_tenant_id_memberships FOREIGN KEY(tenant_id, user_id)
                REFERENCES memberships (tenant_id, user_id),
            CONSTRAINT ck_phone_links_valid_phone CHECK (phone ~ '^\+[1-9][0-9]{6,14}$'),
            CONSTRAINT ck_phone_links_valid_token_hash CHECK (token_hash ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute("CREATE INDEX ix_phone_links_tenant_id ON phone_links (tenant_id)")
    op.execute(
        r"""
        CREATE UNIQUE INDEX uq_phone_links_verified_phone ON phone_links (phone) WHERE verified_at
            IS NOT NULL AND revoked_at IS NULL
        """
    )
    op.execute(
        r"""
        CREATE TABLE conversations (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            phone_link_id UUID NOT NULL,
            user_id UUID NOT NULL,
            last_inbound_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_conversations PRIMARY KEY (id),
            CONSTRAINT uq_conversations_tenant_id_id UNIQUE (tenant_id, id),
            CONSTRAINT uq_conversations_tenant_id_id_user UNIQUE (tenant_id, id, user_id),
            CONSTRAINT uq_conversations_tenant_id_id_link_user UNIQUE (tenant_id, id, phone_link_id,
                user_id),
            CONSTRAINT uq_conversations_tenant_link UNIQUE (tenant_id, phone_link_id),
            CONSTRAINT fk_conversations_tenant_id_phone_links FOREIGN KEY(tenant_id, phone_link_id,
                user_id) REFERENCES phone_links (tenant_id, id, user_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_conversations_tenant_id ON conversations (tenant_id)")
    op.execute(
        r"""
        CREATE TABLE messages (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            conversation_id UUID NOT NULL,
            phone_link_id UUID NOT NULL,
            user_id UUID NOT NULL,
            direction VARCHAR(8) NOT NULL,
            body TEXT NOT NULL,
            twilio_sid VARCHAR(34),
            account_sid VARCHAR(34) NOT NULL,
            status VARCHAR(32) DEFAULT 'received' NOT NULL,
            processing_error VARCHAR(64),
            received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            processed_at TIMESTAMP WITH TIME ZONE,
            reply_to_id UUID,
            processing_attempts INTEGER DEFAULT '0' NOT NULL,
            available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_messages PRIMARY KEY (id),
            CONSTRAINT uq_messages_tenant_id_id UNIQUE (tenant_id, id),
            CONSTRAINT uq_messages_tenant_id_id_link UNIQUE (tenant_id, id, phone_link_id),
            CONSTRAINT uq_messages_twilio_sid UNIQUE (twilio_sid),
            CONSTRAINT uq_messages_reply_to_id UNIQUE (reply_to_id),
            CONSTRAINT fk_messages_tenant_id_conversations FOREIGN KEY(tenant_id, conversation_id,
                phone_link_id, user_id) REFERENCES conversations (tenant_id, id, phone_link_id,
                user_id),
            CONSTRAINT fk_messages_tenant_id_messages FOREIGN KEY(tenant_id, reply_to_id) REFERENCES
                messages (tenant_id, id),
            CONSTRAINT ck_messages_valid_direction CHECK (direction IN ('inbound', 'outbound')),
            CONSTRAINT ck_messages_valid_body CHECK (length(body) BETWEEN 1 AND 4096),
            CONSTRAINT ck_messages_valid_twilio_sid CHECK (twilio_sid IS NULL OR twilio_sid ~
                '^(SM|MM)[0-9a-fA-F]{32}$'),
            CONSTRAINT ck_messages_valid_account_sid CHECK (account_sid ~ '^AC[0-9a-fA-F]{32}$'),
            CONSTRAINT ck_messages_valid_reply CHECK (reply_to_id IS NULL OR direction =
                'outbound'),
            CONSTRAINT ck_messages_nonnegative_processing_attempts CHECK (processing_attempts >= 0)
        )
        """
    )
    op.execute(
        r"""
        CREATE INDEX ix_messages_tenant_conversation ON messages (tenant_id, conversation_id)
        """
    )
    op.execute(
        r"""
        CREATE TABLE outbox (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            message_id UUID NOT NULL,
            phone_link_id UUID NOT NULL,
            status VARCHAR(16) DEFAULT 'pending' NOT NULL,
            attempts INTEGER DEFAULT '0' NOT NULL,
            available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            lease_until TIMESTAMP WITH TIME ZONE,
            dispatch_started_at TIMESTAMP WITH TIME ZONE,
            last_error VARCHAR(64),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_outbox PRIMARY KEY (id),
            CONSTRAINT uq_outbox_tenant_id_id UNIQUE (tenant_id, id),
            CONSTRAINT uq_outbox_message_id UNIQUE (message_id),
            CONSTRAINT fk_outbox_tenant_id_messages FOREIGN KEY(tenant_id, message_id,
                phone_link_id) REFERENCES messages (tenant_id, id, phone_link_id),
            CONSTRAINT fk_outbox_tenant_id_phone_links FOREIGN KEY(tenant_id, phone_link_id)
                REFERENCES phone_links (tenant_id, id),
            CONSTRAINT ck_outbox_valid_status CHECK (status IN ('pending', 'dispatching', 'retry',
                'sent', 'uncertain', 'failed', 'blocked')),
            CONSTRAINT ck_outbox_nonnegative_attempts CHECK (attempts >= 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_outbox_tenant_id ON outbox (tenant_id)")
    op.execute(
        r"""
        CREATE TABLE message_jobs (
            id UUID NOT NULL,
            kind VARCHAR(8) NOT NULL,
            entity_id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            phone_link_id UUID NOT NULL,
            issuer VARCHAR(512) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            message_id UUID,
            outbox_id UUID,
            due_at TIMESTAMP WITH TIME ZONE NOT NULL,
            ready BOOLEAN NOT NULL,
            last_error VARCHAR(64),
            CONSTRAINT pk_message_jobs PRIMARY KEY (id),
            CONSTRAINT fk_message_jobs_tenant_id_phone_links FOREIGN KEY(tenant_id, phone_link_id)
                REFERENCES phone_links (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_message_jobs_tenant_id_messages FOREIGN KEY(tenant_id, message_id)
                REFERENCES messages (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_message_jobs_tenant_id_outbox FOREIGN KEY(tenant_id, outbox_id) REFERENCES
                outbox (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_message_jobs_valid_kind CHECK (kind IN ('inbound', 'outbound')),
            CONSTRAINT ck_message_jobs_entity_identity CHECK (id = entity_id),
            CONSTRAINT ck_message_jobs_valid_entity CHECK ((kind = 'inbound' AND message_id =
                entity_id AND outbox_id IS NULL) OR (kind = 'outbound' AND outbox_id = entity_id AND
                message_id IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX ix_message_jobs_ready_due ON message_jobs (ready, due_at)")
    install_security()


def install_security() -> None:
    # Source writes and their queue discovery index commit in the same transaction.
    for table in ("phone_links", "conversations", "messages", "outbox"):
        op.execute(
            f"CREATE TRIGGER touch_updated_at BEFORE UPDATE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at()"
        )
    for table in ("phone_links", "conversations", "messages", "outbox", "message_jobs"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")

    own_link = """
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        AND EXISTS (SELECT 1 FROM public.users WHERE users.id = phone_links.user_id)
        AND EXISTS (SELECT 1 FROM public.businesses WHERE businesses.id = phone_links.tenant_id)
        AND issuer = NULLIF(current_setting('app.issuer', true), '')
        AND subject = NULLIF(current_setting('app.subject', true), '')
    """
    own_link_writer = (
        own_link
        + """
        AND EXISTS (SELECT 1 FROM public.memberships
                    WHERE memberships.tenant_id = phone_links.tenant_id
                      AND memberships.user_id = phone_links.user_id
                      AND memberships.role IN ('owner', 'staff'))
    """
    )
    install_tenant_policies("phone_links", own_link, own_link_writer)
    for table in ("conversations", "messages", "outbox"):
        member = f"""
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            AND EXISTS (SELECT 1 FROM public.phone_links
                         WHERE phone_links.tenant_id = {table}.tenant_id
                           AND phone_links.id = {table}.phone_link_id)
        """
        writer = (
            member
            + f"""
            AND EXISTS (SELECT 1 FROM public.memberships
                         WHERE memberships.tenant_id = {table}.tenant_id
                           AND memberships.role IN ('owner', 'staff'))
        """
        )
        install_tenant_policies(table, member, writer)

    # FORCE RLS also applies to a non-superuser table owner. Explicitly permit
    # owner access to routing metadata only; message content has no such policy.
    for table in ("phone_links", "message_jobs"):
        owner = f"""
            current_user = pg_catalog.pg_get_userbyid((
                SELECT c.relowner FROM pg_catalog.pg_class c
                 WHERE c.oid = 'public.{table}'::pg_catalog.regclass))
        """
        op.execute(
            f"CREATE POLICY {table}_gateway_owner ON public.{table} "
            f"FOR ALL USING ({owner}) WITH CHECK ({owner})"
        )

    op.execute(
        """
        CREATE FUNCTION public.messaging_guard_phone_link() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
        DECLARE
            owner_name name;
        BEGIN
            SELECT pg_catalog.pg_get_userbyid(c.relowner) INTO owner_name
              FROM pg_catalog.pg_class c WHERE c.oid = TG_RELID;
            IF current_user = owner_name THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.verified_at IS NOT NULL OR NEW.revoked_at IS NOT NULL
                   OR NEW.token_hash IS NULL THEN
                    RAISE EXCEPTION 'invalid phone link state' USING ERRCODE = '23514';
                END IF;
            ELSE
                IF ROW(NEW.id, NEW.tenant_id, NEW.user_id, NEW.phone, NEW.issuer,
                       NEW.subject, NEW.expires_at, NEW.verified_at, NEW.created_at)
                   IS DISTINCT FROM
                   ROW(OLD.id, OLD.tenant_id, OLD.user_id, OLD.phone, OLD.issuer,
                       OLD.subject, OLD.expires_at, OLD.verified_at, OLD.created_at)
                   OR (OLD.revoked_at IS NOT NULL
                       AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
                   OR (NEW.token_hash IS DISTINCT FROM OLD.token_hash
                       AND NOT (NEW.token_hash IS NULL AND NEW.revoked_at IS NOT NULL)) THEN
                    RAISE EXCEPTION 'invalid phone link state' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER messaging_guard_phone_link BEFORE INSERT OR UPDATE "
        "ON public.phone_links FOR EACH ROW "
        "EXECUTE FUNCTION public.messaging_guard_phone_link()"
    )
    op.execute(
        """
        CREATE FUNCTION public.messaging_route_phone(phone_value text)
        RETURNS TABLE(tenant_id uuid, link_id uuid, issuer text, subject text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT l.tenant_id, l.id, l.issuer::text, l.subject::text
              FROM public.phone_links l
             WHERE l.phone = phone_value AND l.verified_at IS NOT NULL
               AND l.revoked_at IS NULL
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.messaging_redeem_phone(phone_value text, digest_value text)
        RETURNS TABLE(tenant_id uuid, link_id uuid, issuer text, subject text)
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
            UPDATE public.phone_links l
               SET verified_at = statement_timestamp(), token_hash = NULL
             WHERE l.phone = phone_value AND l.token_hash = digest_value
               AND l.verified_at IS NULL AND l.revoked_at IS NULL
               AND l.expires_at > statement_timestamp()
            RETURNING l.tenant_id, l.id, l.issuer::text, l.subject::text
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.messaging_lookup_job(job_value uuid)
        RETURNS TABLE(job_id uuid, kind text, entity_id uuid, tenant_id uuid,
                      link_id uuid, issuer text, subject text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT j.id, j.kind::text, j.entity_id, j.tenant_id,
                   j.phone_link_id, j.issuer::text, j.subject::text
              FROM public.message_jobs j WHERE j.id = job_value
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.messaging_discover_jobs(batch_size integer DEFAULT 100)
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
    op.execute(
        """
        CREATE FUNCTION public.messaging_park_job(job_value uuid) RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
            UPDATE public.message_jobs SET ready = false, last_error = 'access_revoked'
             WHERE id = job_value
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.messaging_index_inbound() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            IF NEW.direction = 'inbound' THEN
                INSERT INTO public.message_jobs
                    (id, kind, entity_id, tenant_id, phone_link_id, issuer, subject,
                     message_id, outbox_id, due_at, ready)
                SELECT NEW.id, 'inbound', NEW.id, NEW.tenant_id, NEW.phone_link_id,
                       l.issuer, l.subject, NEW.id, NULL, NEW.available_at,
                       NEW.processed_at IS NULL AND NEW.status NOT IN ('failed', 'blocked')
                  FROM public.phone_links l
                 WHERE l.id = NEW.phone_link_id AND l.tenant_id = NEW.tenant_id
                ON CONFLICT (id) DO UPDATE
                    SET due_at = EXCLUDED.due_at, ready = EXCLUDED.ready, last_error = NULL;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.messaging_index_outbound() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            INSERT INTO public.message_jobs
                (id, kind, entity_id, tenant_id, phone_link_id, issuer, subject,
                 message_id, outbox_id, due_at, ready)
            SELECT NEW.id, 'outbound', NEW.id, NEW.tenant_id, NEW.phone_link_id,
                   l.issuer, l.subject, NULL, NEW.id,
                   CASE WHEN NEW.status = 'dispatching'
                        THEN COALESCE(NEW.lease_until, statement_timestamp())
                        ELSE NEW.available_at END,
                   NEW.status IN ('pending', 'retry', 'dispatching')
              FROM public.phone_links l
             WHERE l.id = NEW.phone_link_id AND l.tenant_id = NEW.tenant_id
            ON CONFLICT (id) DO UPDATE
                SET due_at = EXCLUDED.due_at, ready = EXCLUDED.ready, last_error = NULL;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER messaging_index_inbound AFTER INSERT OR UPDATE ON public.messages "
        "FOR EACH ROW EXECUTE FUNCTION public.messaging_index_inbound()"
    )
    op.execute(
        "CREATE TRIGGER messaging_index_outbound AFTER INSERT OR UPDATE ON public.outbox "
        "FOR EACH ROW EXECUTE FUNCTION public.messaging_index_outbound()"
    )
    # PostgreSQL grants EXECUTE to PUBLIC by default. Triggers need no runtime
    # direct EXECUTE permission; only the exact gateway signatures are granted
    # separately by the reviewed grant helper.
    for function in (
        "touch_updated_at()",
        "messaging_route_phone(text)",
        "messaging_redeem_phone(text,text)",
        "messaging_lookup_job(uuid)",
        "messaging_discover_jobs(integer)",
        "messaging_park_job(uuid)",
        "messaging_index_inbound()",
        "messaging_index_outbound()",
        "messaging_guard_phone_link()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC")


def install_tenant_policies(table: str, member: str, writer: str) -> None:
    op.execute(f"CREATE POLICY {table}_read_member ON public.{table} FOR SELECT USING ({member})")
    op.execute(
        f"CREATE POLICY {table}_insert_writer ON public.{table} FOR INSERT WITH CHECK ({writer})"
    )
    op.execute(
        f"CREATE POLICY {table}_update_writer ON public.{table} "
        f"FOR UPDATE USING ({writer}) WITH CHECK ({writer})"
    )


def downgrade() -> None:
    # Source-table triggers disappear with their tables; policies referencing
    # phone_links must disappear before that routing metadata is removed.
    for table in ("message_jobs", "outbox", "messages", "conversations", "phone_links"):
        op.drop_table(table)
    for function in (
        "messaging_route_phone(text)",
        "messaging_redeem_phone(text,text)",
        "messaging_lookup_job(uuid)",
        "messaging_discover_jobs(integer)",
        "messaging_park_job(uuid)",
        "messaging_index_inbound()",
        "messaging_index_outbound()",
        "messaging_guard_phone_link()",
    ):
        op.execute(f"DROP FUNCTION public.{function}")
    # Restore the exact Milestone 1 function privilege when rolling back.
    op.execute("GRANT EXECUTE ON FUNCTION public.touch_updated_at() TO PUBLIC")
