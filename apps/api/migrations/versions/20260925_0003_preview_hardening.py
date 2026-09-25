"""Harden identity resolution and runtime grants for preview development."""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260925_0003"
down_revision = "20260924_0002"
branch_labels = None
depends_on = None

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

        DROP FUNCTION IF EXISTS app.resolve_memberships(text);

        CREATE FUNCTION app.resolve_memberships(oidc_subject text)
        RETURNS TABLE (user_id uuid, tenant_id uuid, role text)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT u.id, m.tenant_id, m.role
            FROM public.memberships AS m
            JOIN public.users AS u
              ON u.tenant_id = m.tenant_id
             AND u.id = m.user_id
            WHERE u.oidc_subject = $1
              AND u.deleted_at IS NULL
              AND m.active
              AND m.deleted_at IS NULL
        $$;
        REVOKE ALL ON FUNCTION app.resolve_memberships(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.resolve_memberships(text) TO {_RUNTIME_ROLE};

        REVOKE UPDATE ON tenants, users, memberships FROM {_RUNTIME_ROLE};
        REVOKE DELETE ON users, memberships FROM {_RUNTIME_ROLE};
        REVOKE UPDATE ON sources FROM {_RUNTIME_ROLE};
        GRANT UPDATE (title, page_count, status) ON sources TO {_RUNTIME_ROLE};
        """
    )


def downgrade() -> None:
    execute_script(
        f"""
        REVOKE UPDATE (title, page_count, status) ON sources FROM {_RUNTIME_ROLE};
        GRANT UPDATE ON sources TO {_RUNTIME_ROLE};
        GRANT UPDATE ON tenants, users, memberships TO {_RUNTIME_ROLE};
        GRANT DELETE ON users, memberships TO {_RUNTIME_ROLE};
        DROP FUNCTION IF EXISTS app.resolve_memberships(text);
        CREATE FUNCTION app.resolve_memberships(oidc_subject text)
        RETURNS TABLE (tenant_id uuid, role text)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT m.tenant_id, m.role
            FROM public.memberships AS m
            JOIN public.users AS u
              ON u.tenant_id = m.tenant_id
             AND u.id = m.user_id
            WHERE u.oidc_subject = $1
              AND u.deleted_at IS NULL
              AND m.active
              AND m.deleted_at IS NULL
        $$;
        REVOKE ALL ON FUNCTION app.resolve_memberships(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.resolve_memberships(text) TO {_RUNTIME_ROLE};
        """
    )
