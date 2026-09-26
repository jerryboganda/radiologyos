#!/usr/bin/env bash
# Nightly off-host copy of radiologyos to Google Drive (rclone remote "gdrive:").
#
# Owner decision 2026-09-26: use the same Drive as the OET backup, in its own
# folder. Pattern follows /root/oetwebsite/scripts/db-nightly-backup-gdrive.sh:
# upload, verify, and only then prune, so there is never zero remote copies.
#
#   db/<YYYYMMDD>/{radiologyos,keycloak}.dump  - from the platform nightly set
#       (checksums verified against its MANIFEST before and after upload);
#       the newest KEEP_DB_DAYS sets are kept.
#   objects/current/                          - mirror of the MinIO bucket
#   objects/deleted/<YYYYMMDD>/               - objects removed from the bucket
#       that day; kept KEEP_DELETED_DAYS so an accidental delete is recoverable.
#
# Install: /opt/radiologyos/offsite-backup-gdrive.sh, host cron 03:30 local
# (after platform-backup at 00:45 UTC). Logs ids, sizes, and counts only.
set -euo pipefail

REMOTE="${GDRIVE_REMOTE:-gdrive}"
DEST="${GDRIVE_DIR:-radiologyos-backups}"
NIGHTLY=/opt/platform/backups/nightly
PROJECT_ENV=/opt/platform/projects/radiologyos.env
DBS="radiologyos keycloak"
KEEP_DB_DAYS="${KEEP_DB_DAYS:-14}"
KEEP_DELETED_DAYS="${KEEP_DELETED_DAYS:-30}"
TODAY=$(date -u +%Y%m%d)

log() { echo "[$(date -u +%FT%TZ)] $*"; }

rclone listremotes | grep -qx "${REMOTE}:" || { log "ERROR: rclone remote ${REMOTE} missing"; exit 1; }

# --- 1. databases -----------------------------------------------------------
DAY=$(find "$NIGHTLY" -mindepth 2 -maxdepth 2 -name radiologyos.dump -printf '%h\n' \
  | sort | tail -1 | xargs -r basename)
[ -n "$DAY" ] || { log "ERROR: no radiologyos.dump under $NIGHTLY"; exit 2; }
SRC="$NIGHTLY/$DAY"
for db in $DBS; do
  size=$(stat -c%s "$SRC/$db.dump")
  [ "$size" -ge 10000 ] || { log "ERROR: $db.dump suspiciously small ($size bytes)"; exit 3; }
  (cd "$SRC" && grep " $db.dump\$" MANIFEST.sha256 | sha256sum -c --quiet -) \
    || { log "ERROR: $db.dump fails its manifest"; exit 4; }
  rclone copyto "$SRC/$db.dump" "$REMOTE:$DEST/db/$DAY/$db.dump" --stats-one-line
  # Drive stores md5; rclone recomputes it locally and compares.
  rclone check "$SRC" "$REMOTE:$DEST/db/$DAY" --include "$db.dump" --one-way -q \
    || { log "ERROR: upload verification failed for $db; nothing pruned"; exit 5; }
  log "db $db day=$DAY bytes=$size verified"
done

rclone lsf --dirs-only "$REMOTE:$DEST/db/" | tr -d / | { grep -E '^[0-9]{8}$' || true; } | sort -r \
  | tail -n +"$((KEEP_DB_DAYS + 1))" | while read -r old; do
      log "pruning db/$old"
      rclone purge "$REMOTE:$DEST/db/$old"
    done

# --- 2. object store --------------------------------------------------------
# Credentials go to rclone through its environment only, never argv or logs.
set -a; . "$PROJECT_ENV"; set +a
export RCLONE_CONFIG_RADMINIO_TYPE=s3 RCLONE_CONFIG_RADMINIO_PROVIDER=Minio
export RCLONE_CONFIG_RADMINIO_ENDPOINT="$PLATFORM_S3_LOOPBACK"
export RCLONE_CONFIG_RADMINIO_ACCESS_KEY_ID="$PLATFORM_S3_ACCESS_KEY"
export RCLONE_CONFIG_RADMINIO_SECRET_ACCESS_KEY="$PLATFORM_S3_SECRET_KEY"
nice -n 10 ionice -c3 rclone sync "radminio:$PLATFORM_S3_BUCKET" "$REMOTE:$DEST/objects/current" \
  --backup-dir "$REMOTE:$DEST/objects/deleted/$TODAY" \
  --transfers 2 --checkers 4 --bwlimit 8M --fast-list --stats-one-line --stats 0
log "objects mirrored bucket=$PLATFORM_S3_BUCKET"

{ rclone lsf --dirs-only "$REMOTE:$DEST/objects/deleted/" 2>/dev/null || true; } | tr -d / \
  | { grep -E '^[0-9]{8}$' || true; } | while read -r day; do
      if [ "$day" -lt "$(date -u -d "-$KEEP_DELETED_DAYS days" +%Y%m%d)" ]; then
        log "pruning objects/deleted/$day"
        rclone purge "$REMOTE:$DEST/objects/deleted/$day"
      fi
    done

date -u +%FT%TZ > /opt/radiologyos/offsite-backup.last-success
log "done"
