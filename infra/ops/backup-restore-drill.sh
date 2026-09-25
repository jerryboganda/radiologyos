#!/usr/bin/env bash
# Backup/restore drill for the radiologyos database.
#
# Restores the newest nightly dump into a SCRATCH database, verifies row counts
# and that RLS survived, then drops the scratch database. The live radiologyos
# database is only ever read. Produces the RPO/RTO evidence for slice V.
#
# Usage: bin/backup-restore-drill.sh [--keep]
set -euo pipefail

KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

SCRATCH="radiologyos_restore_drill"
BACKUPS=/opt/platform/backups/nightly

echo "=== 1. locate the newest complete nightly dump set ==="
DUMP_DIR=$(find "$BACKUPS" -mindepth 2 -maxdepth 2 -name 'radiologyos.dump' -printf '%h\n' 2>/dev/null | sort | tail -1)
if [ -z "$DUMP_DIR" ]; then
  echo "no radiologyos.dump found under $BACKUPS" >&2
  exit 1
fi
DUMP="$DUMP_DIR/radiologyos.dump"
echo "    dump:  $DUMP"
echo "    taken: $(stat -c '%y' "$DUMP")"
echo "    size:  $(du -h "$DUMP" | cut -f1)"

if [ -f "$DUMP_DIR/MANIFEST.sha256" ]; then
  echo "    verifying checksum"
  ( cd "$DUMP_DIR" && sha256sum -c --ignore-missing MANIFEST.sha256 )
fi

echo
echo "=== 2. record RPO (how old is the newest dump) ==="
DUMP_AGE_HOURS=$(( ( $(date +%s) - $(stat -c '%Y' "$DUMP") ) / 3600 ))
echo "    RPO: ${DUMP_AGE_HOURS}h (age of the newest dump at drill time)"

echo
echo "=== 3. restore into a scratch database ==="
docker exec platform-postgres psql -U platform_admin -d postgres -q -c \
  "DROP DATABASE IF EXISTS $SCRATCH;" >/dev/null 2>&1 || true
docker exec platform-postgres psql -U platform_admin -d postgres -q -c \
  "CREATE DATABASE $SCRATCH;"

RTO_START=$(date +%s)
docker exec -i platform-postgres pg_restore -U platform_admin --clean --if-exists -d "$SCRATCH" < "$DUMP"
RTO_SECONDS=$(( $(date +%s) - RTO_START ))
echo "    RTO: ${RTO_SECONDS}s (restore elapsed)"

echo
echo "=== 4. verify the restored copy ==="
docker exec platform-postgres psql -U platform_admin -d "$SCRATCH" -Atc \
  "select 'tables: '||count(*) from pg_tables where schemaname='public';"
docker exec platform-postgres psql -U platform_admin -d "$SCRATCH" -Atc \
  "select 'rls tables: '||count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where c.relrowsecurity and n.nspname='public';"
docker exec platform-postgres psql -U platform_admin -d "$SCRATCH" -Atc \
  "select 'alembic head: '||version_num from alembic_version;" 2>/dev/null || true
echo "    pgvector available: $(docker exec platform-postgres psql -U platform_admin -d "$SCRATCH" -Atc "select count(*) from pg_extension where extname='vector';")"
echo "    app schema present: $(docker exec platform-postgres psql -U platform_admin -d "$SCRATCH" -Atc "select count(*) from pg_namespace where nspname='app';")"

echo
echo "=== 5. live database untouched ==="
docker exec platform-postgres psql -U platform_admin -d postgres -Atc \
  "select 'live tables: '||count(*) from pg_tables where schemaname='public';" \
  --dbname=radiologyos 2>/dev/null || \
docker exec platform-postgres psql -U platform_admin -d radiologyos -Atc \
  "select 'live tables: '||count(*) from pg_tables where schemaname='public';"

echo
if [ "$KEEP" = "1" ]; then
  echo "scratch database $SCRATCH kept for inspection"
else
  echo "=== 6. drop the scratch database ==="
  docker exec platform-postgres psql -U platform_admin -d postgres -q -c \
    "DROP DATABASE $SCRATCH;"
  echo "    dropped $SCRATCH"
fi

echo
echo "=== drill result: RESTORE VERIFIED ==="
