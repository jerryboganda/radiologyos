"""Push reminders: subscriptions, per-user settings, and a due-reminder resolver.

Expand-only. Both tables are tenant-scoped with ENABLE + FORCE RLS (two-tenant
proof in evals/checks/test_notifications_live.py). The worker needs to know
*which* users are due without reading any tenant's data, so a narrow SECURITY
DEFINER function returns only (tenant_id, user_id) pairs whose local reminder
time has passed today; everything else is read under that tenant's context.

Revision ID: 20260926_0009
Revises: 20260926_0008
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0009"
down_revision = "20260926_0008"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"


def upgrade() -> None:
    execute_script(
        f"""
        DO $$
        BEGIN
            IF current_user <> '{_MIGRATOR_ROLE}' THEN
                RAISE EXCEPTION 'migrations must run as %', '{_MIGRATOR_ROLE}';
            END IF;
        END
        $$;

        CREATE TABLE push_subscriptions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            endpoint text NOT NULL CHECK (endpoint LIKE 'https://%' AND length(endpoint) < 2048),
            p256dh text NOT NULL CHECK (length(p256dh) < 256),
            auth text NOT NULL CHECK (length(auth) < 128),
            user_agent text CHECK (user_agent IS NULL OR length(user_agent) <= 300),
            failures integer NOT NULL DEFAULT 0 CHECK (failures >= 0),
            last_success_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, endpoint),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id)
        );

        CREATE TABLE notification_settings (
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            enabled boolean NOT NULL DEFAULT true,
            reminder_time time NOT NULL DEFAULT '19:00',
            timezone text NOT NULL DEFAULT 'Asia/Karachi'
                CHECK (length(timezone) BETWEEN 1 AND 64),
            channels jsonb NOT NULL DEFAULT '["push"]'::jsonb
                CHECK (jsonb_typeof(channels) = 'array'),
            include_due_cards boolean NOT NULL DEFAULT true,
            include_plan boolean NOT NULL DEFAULT true,
            last_sent_on date,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, user_id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id)
        );

        CREATE INDEX push_subscriptions_user_idx ON push_subscriptions (tenant_id, user_id);
        CREATE TRIGGER notification_settings_touch_updated_at
            BEFORE UPDATE ON notification_settings
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )
    for table in ("push_subscriptions", "notification_settings"):
        execute_script(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            REVOKE ALL ON {table} FROM PUBLIC;
            CREATE POLICY {table}_tenant_all ON {table}
                FOR ALL USING (
                    tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
                ) WITH CHECK (
                    tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
                );
            """
        )
    # Only the due-reminder resolver (SECURITY DEFINER, owned by the migrator)
    # reads settings across tenants, and it returns ids only.
    execute_script(
        f"""
        CREATE POLICY notification_settings_migrator_resolver_read ON notification_settings
            FOR SELECT TO {_MIGRATOR_ROLE} USING (true);
        """
    )
    execute_script(
        f"""
        CREATE FUNCTION app.due_reminders(at_time timestamptz)
        RETURNS TABLE (tenant_id uuid, user_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT s.tenant_id, s.user_id
            FROM public.notification_settings AS s
            WHERE s.enabled
              AND (at_time AT TIME ZONE s.timezone)::time >= s.reminder_time
              AND (s.last_sent_on IS NULL
                   OR s.last_sent_on < (at_time AT TIME ZONE s.timezone)::date)
        $$;
        REVOKE ALL ON FUNCTION app.due_reminders(timestamptz) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.due_reminders(timestamptz) TO {_RUNTIME_ROLE};
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON push_subscriptions, notification_settings TO {_RUNTIME_ROLE};
        """
    )


def downgrade() -> None:
    execute_script(
        """
        DROP FUNCTION IF EXISTS app.due_reminders(timestamptz);
        DROP TABLE IF EXISTS notification_settings;
        DROP TABLE IF EXISTS push_subscriptions;
        """
    )
