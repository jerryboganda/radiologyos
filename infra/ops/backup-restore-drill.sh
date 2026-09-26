#!/usr/bin/env bash
# Backup/restore drill for the radiologyos database (ADR 0008, amended by ADR 0022).
#
# Restores the newest nightly dump into a SCRATCH database and ASSERTS, exiting
# non-zero on any failure:
#   * the dump set's checksums verify;
#   * the restored alembic head equals the expected head, and so does the live one;
#   * every public table with a tenant_id column (plus tenants) has ENABLE + FORCE
#     row-level security, and the restored copy has as many as the live database;
#   * the vector and pg_trgm extensions and the app schema exist.
# If keycloak.dump is in the same set, it is restored into a second scratch
# database and must contain the radbrain realm.
#
# The live databases are only ever read. Scratch databases are dropped on exit
# unless --keep is given. Prints RPO (dump age) and RTO (restore time).
#
# Expected head, first match wins:
#   EXPECTED_HEAD=<revision>        explicit
#   MIGRATIONS_DIR=<dir>            derived from a checkout's migration files
#   API_CONTAINER (default radiologyos-api-1)
#                                   derived from the migrations baked into the
#                                   deployed api image, i.e. the deployed revision
#
# Usage: backup-restore-drill.sh [--keep]
set -euo pipefail

KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

SCRATCH="radiologyos_restore_drill"
KC_SCRATCH="keycloak_restore_drill"
LIVE="radiologyos"
BACKUPS="${BACKUPS:-/opt/platform/backups/nightly}"
API_CONTAINER="${API_CONTAINER:-radiologyos-api-1}"
IMAGE_MIGRATIONS=/srv/apps/api/migrations/versions
FAILURES=0

TENANT_TABLES_WHERE="n.nspname = 'public' AND c.relkind IN ('r', 'p') AND (
  c.relname = 'tenants' OR EXISTS (
    SELECT 1 FROM pg_attribute AS a WHERE a.attrelid = c.oid
      AND a.attname = 'tenant_id' AND a.attnum > 0 AND NOT a.attisdropped))"

sql() {  # sql <database> <statement> - read-only helper, tuples only
  docker exec platform-postgres psql -U platform_admin -d "$1" -v ON_ERROR_STOP=1 -Atc "$2"
}

check() {  # check <label> <detail> <command...>: PASS when the command succeeds
  local label="$1" detail="$2"
  shift 2
  if "$@"; then
    echo "    [PASS] $label${detail:+ - $detail}"
  else
    echo "    [FAIL] $label${detail:+ - $detail}"
    FAILURES=$((FAILURES + 1))
  fi
}

positive_and_equal() { [ "$1" -gt 0 ] 2>/dev/null && [ "$1" = "$2" ]; }
single_word() { [ -n "$1" ] && [ "$(wc -w <<< "$1")" = "1" ]; }
checksums_ok() { ( cd "$DUMP_DIR" && sha256sum -c --ignore-missing --quiet MANIFEST.sha256 ); }

drop_scratch() {
  [ "$KEEP" = "1" ] && return 0
  sql postgres "DROP DATABASE IF EXISTS $SCRATCH;" >/dev/null 2>&1 || true
  sql postgres "DROP DATABASE IF EXISTS $KC_SCRATCH;" >/dev/null 2>&1 || true
}
trap drop_scratch EXIT

head_from_sources() {  # stdin: migration sources; prints the single unreferenced revision
  awk -F'"' '/^revision = "/ { rev[$2] = 1 } /^down_revision = "/ { down[$2] = 1 }
    END { for (r in rev) if (!(r in down)) print r }'
}

expected_head() {
  if [ -n "${EXPECTED_HEAD:-}" ]; then
    echo "$EXPECTED_HEAD|EXPECTED_HEAD"
  elif [ -n "${MIGRATIONS_DIR:-}" ]; then
    echo "$(cat "$MIGRATIONS_DIR"/*.py | head_from_sources)|$MIGRATIONS_DIR"
  else
    echo "$(docker exec "$API_CONTAINER" sh -c "cat $IMAGE_MIGRATIONS/*.py" \
      | head_from_sources)|$API_CONTAINER image"
  fi
}

locate_dump() {
  DUMP_DIR=$(find "$BACKUPS" -mindepth 2 -maxdepth 2 -name 'radiologyos.dump' -printf '%h\n' \
    2>/dev/null | sort | tail -1)
  if [ -z "$DUMP_DIR" ]; then
    echo "no radiologyos.dump found under $BACKUPS" >&2
    exit 1
  fi
  DUMP="$DUMP_DIR/radiologyos.dump"
  echo "    dump:  $DUMP"
  echo "    taken: $(stat -c '%y' "$DUMP")"
  echo "    size:  $(du -h "$DUMP" | cut -f1)"
  if [ -f "$DUMP_DIR/MANIFEST.sha256" ]; then
    check "dump set checksums verify" "" checksums_ok
  else
    check "dump set has MANIFEST.sha256" "" false
  fi
  RPO_HOURS=$(( ( $(date +%s) - $(stat -c '%Y' "$DUMP") ) / 3600 ))
}

restore_radiologyos() {
  sql postgres "DROP DATABASE IF EXISTS $SCRATCH;" >/dev/null
  sql postgres "CREATE DATABASE $SCRATCH;" >/dev/null
  local start
  start=$(date +%s)
  docker exec -i platform-postgres pg_restore -U platform_admin --clean --if-exists \
    -d "$SCRATCH" < "$DUMP"
  RTO_SECONDS=$(( $(date +%s) - start ))
}

tenant_table_count() { sql "$1" "SELECT count(*) FROM pg_class AS c
  JOIN pg_namespace AS n ON n.oid = c.relnamespace WHERE $TENANT_TABLES_WHERE"; }

verify_restored() {
  local expected source restored live unforced tables live_tables ext
  IFS='|' read -r expected source <<< "$(expected_head)"
  check "expected head derived ($source)" "${expected:-none}" single_word "$expected"
  restored=$(sql "$SCRATCH" "SELECT string_agg(version_num, ',') FROM alembic_version") || restored=""
  live=$(sql "$LIVE" "SELECT string_agg(version_num, ',') FROM alembic_version") || live=""
  check "restored alembic head = expected" "$restored" test "$restored" = "$expected"
  check "live alembic head = expected" "$live" test "$live" = "$expected"
  tables=$(tenant_table_count "$SCRATCH") || tables=0
  live_tables=$(tenant_table_count "$LIVE") || live_tables=0
  check "tenant tables restored" "restored $tables, live $live_tables" \
    positive_and_equal "$tables" "$live_tables"
  unforced=$(sql "$SCRATCH" "SELECT coalesce(string_agg(c.relname, ','), '') FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE $TENANT_TABLES_WHERE AND NOT (c.relrowsecurity AND c.relforcerowsecurity)") \
    || unforced="query failed"
  check "every tenant table has ENABLE + FORCE RLS" "${unforced:-none missing}" \
    test -z "$unforced"
  for ext in vector pg_trgm; do
    check "extension $ext present" "" test \
      "$(sql "$SCRATCH" "SELECT count(*) FROM pg_extension WHERE extname = '$ext'")" = "1"
  done
  check "app schema present" "" test \
    "$(sql "$SCRATCH" "SELECT count(*) FROM pg_namespace WHERE nspname = 'app'")" = "1"
  RESTORED_HEAD=$restored
  RESTORED_TABLES=$tables
}

verify_keycloak() {
  local kc_dump="$DUMP_DIR/keycloak.dump" realms radbrain
  if [ ! -f "$kc_dump" ]; then
    echo "    keycloak.dump not in this set; Keycloak check skipped"
    KC_RESULT="skipped (no dump)"
    return 0
  fi
  sql postgres "DROP DATABASE IF EXISTS $KC_SCRATCH;" >/dev/null
  sql postgres "CREATE DATABASE $KC_SCRATCH;" >/dev/null
  # Ownership and grants are irrelevant to a row-count check, and Keycloak
  # objects may name roles this scratch restore does not need.
  docker exec -i platform-postgres pg_restore -U platform_admin --no-owner --no-acl \
    -d "$KC_SCRATCH" < "$kc_dump" || echo "    pg_restore reported errors; checking rows anyway"
  realms=$(sql "$KC_SCRATCH" "SELECT count(*) FROM realm") || realms=0
  radbrain=$(sql "$KC_SCRATCH" "SELECT count(*) FROM realm WHERE name = 'radbrain'") \
    || radbrain=0
  check "keycloak dump restores the radbrain realm" "$realms realms" test "$radbrain" = "1"
  KC_RESULT="$realms realms, radbrain present=$radbrain"
}

echo "=== 1. locate and checksum the newest complete nightly dump set ==="
locate_dump
echo
echo "=== 2. restore radiologyos into a scratch database ==="
restore_radiologyos
echo "    restored into $SCRATCH in ${RTO_SECONDS}s"
echo
echo "=== 3. assert schema state, RLS and extensions (live database only read) ==="
verify_restored
echo
echo "=== 4. restore the Keycloak dump into a scratch database ==="
verify_keycloak
echo
if [ "$KEEP" = "1" ]; then
  echo "scratch databases kept for inspection: $SCRATCH $KC_SCRATCH"
fi

echo
echo "=== drill summary ==="
echo "    dump set:        $(basename "$DUMP_DIR")"
echo "    RPO:             ${RPO_HOURS}h (age of the newest dump at drill time)"
echo "    RTO:             ${RTO_SECONDS}s (radiologyos restore elapsed)"
echo "    restored head:   $RESTORED_HEAD"
echo "    tenant tables:   $RESTORED_TABLES, all ENABLE + FORCE RLS unless listed above"
echo "    keycloak:        $KC_RESULT"
if [ "$FAILURES" -ne 0 ]; then
  echo "=== drill result: FAILED ($FAILURES check(s)) ==="
  exit 1
fi
echo "=== drill result: RESTORE VERIFIED ==="
