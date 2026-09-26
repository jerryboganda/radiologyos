"""Durable data-rights jobs: account export and account deletion (ADR 0018).

Expand-only. ``data_jobs`` is tenant-scoped with ENABLE + FORCE RLS and a
two-tenant runtime-role proof in evals/checks/test_data_rights_live.py. Two
narrow SECURITY DEFINER functions are added:

* ``app.expired_data_exports(at)`` returns only (tenant_id, job_id) pairs of
  exports past their expiry, so the beat task can find them without reading
  any tenant's rows; everything else runs under that tenant's context.
* ``app.erase_user_identity(user)`` removes the caller-tenant user's identity
  rows (users, memberships, their audit trail), which the runtime role cannot
  touch directly. It refuses unless the current tenant has a *running* delete
  job for that user, and leaves one content-free audit record.

Revision ID: 20260926_0012
Revises: 20260926_0011
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0012"
down_revision = "20260926_0011"
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
        """
    )
    _create_table()
    _create_policies()
    _create_resolver()
    _create_eraser()
    _grant_eraser()


def _create_table() -> None:
    execute_script(
        f"""
        CREATE TABLE data_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            kind text NOT NULL CHECK (kind IN ('export', 'delete')),
            status text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
            step text NOT NULL DEFAULT 'queued' CHECK (length(step) BETWEEN 1 AND 40),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            object_key text CHECK (
                object_key IS NULL
                OR object_key LIKE 'tenants/' || tenant_id::text || '/exports/%'
            ),
            byte_size bigint CHECK (byte_size IS NULL OR byte_size >= 0),
            detail jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
            error_code text CHECK (error_code IS NULL OR length(error_code) <= 100),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            expires_at timestamptz,
            UNIQUE (tenant_id, id),
            CHECK (tenant_id <> '{_CORE}'::uuid),
            CHECK (kind = 'delete' OR expires_at IS NOT NULL)
        );

        CREATE INDEX data_jobs_user_idx ON data_jobs (tenant_id, user_id, kind, created_at DESC);
        CREATE INDEX data_jobs_expiry_idx ON data_jobs (expires_at) WHERE kind = 'export';
        CREATE UNIQUE INDEX data_jobs_one_active_uq ON data_jobs (tenant_id, user_id, kind)
            WHERE status IN ('queued', 'running');
        CREATE TRIGGER data_jobs_touch_updated_at
            BEFORE UPDATE ON data_jobs
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )


def _create_policies() -> None:
    execute_script(
        f"""
        ALTER TABLE data_jobs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE data_jobs FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON data_jobs FROM PUBLIC;
        CREATE POLICY data_jobs_tenant_all ON data_jobs
            FOR ALL USING (
                tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
            ) WITH CHECK (
                tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
            );
        CREATE POLICY data_jobs_migrator_resolver_read ON data_jobs
            FOR SELECT TO {_MIGRATOR_ROLE} USING (true);
        CREATE POLICY audit_log_migrator_erase ON audit_log
            FOR DELETE TO {_MIGRATOR_ROLE} USING (
                tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
            );
        GRANT SELECT, INSERT, UPDATE, DELETE ON data_jobs TO {_RUNTIME_ROLE};
        """
    )


def _create_resolver() -> None:
    execute_script(
        f"""
        CREATE FUNCTION app.expired_data_exports(at_time timestamptz)
        RETURNS TABLE (tenant_id uuid, job_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT j.tenant_id, j.id
            FROM public.data_jobs AS j
            WHERE j.kind = 'export' AND j.expires_at <= at_time
            ORDER BY j.expires_at
            LIMIT 500
        $$;
        REVOKE ALL ON FUNCTION app.expired_data_exports(timestamptz) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.expired_data_exports(timestamptz) TO {_RUNTIME_ROLE};
        """
    )


def _create_eraser() -> None:
    execute_script(
        f"""
        CREATE FUNCTION app.erase_user_identity(target_user uuid)
        RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            ctx uuid := app.current_tenant_id();
            outcome text := 'deleted';
        BEGIN
            IF ctx IS NULL OR ctx = '{_CORE}'::uuid THEN
                RAISE EXCEPTION 'tenant context required' USING ERRCODE = '42501';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.data_jobs AS j
                WHERE j.tenant_id = ctx AND j.user_id = target_user
                  AND j.kind = 'delete' AND j.status = 'running'
            ) THEN
                RAISE EXCEPTION 'no running delete job for this user' USING ERRCODE = '42501';
            END IF;
            DELETE FROM public.audit_log AS a
            WHERE a.tenant_id = ctx AND a.actor_user_id = target_user;
            BEGIN
                DELETE FROM public.memberships AS m
                WHERE m.tenant_id = ctx AND m.user_id = target_user;
                DELETE FROM public.users AS u WHERE u.tenant_id = ctx AND u.id = target_user;
            EXCEPTION WHEN foreign_key_violation THEN
                -- Rows kept for a legal hold still reference the user: keep an
                -- anonymous stub instead (no email, name, or login subject).
                outcome := 'scrubbed';
                UPDATE public.users AS u
                SET email = 'erased-' || u.id::text || '@erased.invalid',
                    display_name = NULL,
                    oidc_subject = 'erased:' || u.id::text,
                    deleted_at = COALESCE(u.deleted_at, now())
                WHERE u.tenant_id = ctx AND u.id = target_user;
                UPDATE public.memberships AS m
                SET active = false, deleted_at = COALESCE(m.deleted_at, now())
                WHERE m.tenant_id = ctx AND m.user_id = target_user;
            END;
            IF NOT EXISTS (
                SELECT 1 FROM public.users AS u WHERE u.tenant_id = ctx AND u.deleted_at IS NULL
            ) THEN
                UPDATE public.tenants AS t
                SET name = 'Deleted account', settings = '{{}}'::jsonb,
                    deleted_at = COALESCE(t.deleted_at, now())
                WHERE t.id = ctx;
            END IF;
            INSERT INTO public.audit_log
                (tenant_id, actor_user_id, action, target_type, target_id, metadata)
            VALUES (ctx, NULL, 'account.erased', 'user', target_user::text,
                    jsonb_build_object('identity', outcome));
            RETURN outcome;
        END
        $$;
        """
    )


def _grant_eraser() -> None:
    execute_script(
        f"""
        REVOKE ALL ON FUNCTION app.erase_user_identity(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.erase_user_identity(uuid) TO {_RUNTIME_ROLE};
        """
    )


def downgrade() -> None:
    execute_script(
        """
        DROP FUNCTION IF EXISTS app.erase_user_identity(uuid);
        DROP FUNCTION IF EXISTS app.expired_data_exports(timestamptz);
        DROP POLICY IF EXISTS audit_log_migrator_erase ON audit_log;
        DROP TABLE IF EXISTS data_jobs;
        """
    )
