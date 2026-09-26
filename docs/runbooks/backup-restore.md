# Backup and restore runbook — radbrain on the shared platform

- Status: current
- Scope: database backup, restore drill, RPO/RTO for the `radiologyos` database
- Related: [production deploy](production-deploy.md),
  [ADR 0007](../decisions/0007-production-on-shared-platform.md),
  `/opt/platform/PLATFORM-RULES.md`

radbrain has no backup job of its own. It relies on the shared platform's
`bin/backup.sh`, which enumerates databases dynamically, so `radiologyos` is
covered from the first night it exists. Do not add a project-local backup.

## How it works

- `platform-backup` runs `bin/backup.sh` daily at 00:45 UTC (02:45 CEST) through
  `bin/backup-loop.sh`, retrying six times five minutes apart while Postgres is
  not ready. Before 2026-09-26 it ran 24 h after container start, and a host
  reboot made it skip a night.
- Each database is dumped with `pg_dump -Fc` into
  `/opt/platform/backups/nightly/<YYYYMMDD>/`, alongside `MANIFEST.sha256`.
- Seven nights are retained. The job aborts if the filesystem drops below a
  15 GB floor, so a full disk cannot silently produce a partial backup set.
- Trigger a run manually with `docker exec platform-backup sh /backup.sh`.

## Verified evidence

Current evidence is recorded per release in `docs/evidence/` (the M0 record is
`docs/evidence/m0.md`), from a drill run on the deployed head. A drill result is only
evidence for the head it printed.

**Historical (2026-09-25, schema `20260925_0003`; superseded).** This run predates
migrations 0004–0014 and the asserting drill. It printed values but asserted nothing,
so it is not evidence for the current schema.

| Measure | Value |
| --- | --- |
| RPO (age of newest dump) | 0h at drill time; 24h worst case between runs |
| RTO (restore elapsed) | 1s for the `radiologyos` database |
| Checksums | all 12 dumps in the set verified `OK` |
| Restored tables | 8, of which 7 with RLS enabled |
| Restored schema state | alembic head `20260925_0003` |
| Extensions / schema | `vector` present, `app` schema present |
| Live database | untouched; the drill only ever reads it |

## Running the drill

The drill restores the newest nightly `radiologyos.dump` into a **scratch** database,
asserts, prints RPO and RTO, then drops the scratch database. It only reads the live
database. It exits non-zero unless all of these hold (ADR 0022):

- the dump set's `MANIFEST.sha256` verifies;
- the restored alembic head **and** the live head equal the expected head;
- every `public` table with a `tenant_id` column (plus `tenants`) has ENABLE + FORCE
  RLS, and the restored copy has as many such tables as the live database;
- the `vector` and `pg_trgm` extensions and the `app` schema exist;
- if `keycloak.dump` is in the same set, it restores into a second scratch database
  and contains the `radbrain` realm.

```bash
/opt/radiologyos/backup-restore-drill.sh          # verify and clean up
/opt/radiologyos/backup-restore-drill.sh --keep   # leave the scratch copies
EXPECTED_HEAD=20260926_0014 /opt/radiologyos/backup-restore-drill.sh
```

The expected head comes from `EXPECTED_HEAD` if it is set. Otherwise it comes from
`MIGRATIONS_DIR` (a checkout's `apps/api/migrations/versions`). Failing both, it comes
from the migrations built into the running `radiologyos-api-1` image, which is the
deployed revision. A deploy that added a migration after the newest dump fails the
drill until a fresh dump exists. Take one first with
`docker exec platform-backup sh /backup.sh`. Copy the script from
`infra/ops/backup-restore-drill.sh` before running it. Paste the drill summary into the
evidence record without editing it.

## Restoring for real

Only when a restore is genuinely required. This **overwrites** the target
database.

```bash
docker exec platform-postgres psql -U platform_admin -d postgres \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE datname='radiologyos' AND pid <> pg_backend_pid();"

docker exec -i platform-postgres pg_restore -U platform_admin \
  --clean --if-exists -d radiologyos \
  < /opt/platform/backups/nightly/<YYYYMMDD>/radiologyos.dump
```

Then redeploy so the application sees a consistent schema:

```bash
cd /opt/radiologyos
docker compose --env-file app.env -f platform.yml run --rm -T migrate < /dev/null
```

## Rollback of a restore

A restore cannot be undone from the dumps. Before restoring, take a fresh dump
of the current state so the restore itself is reversible:

```bash
docker exec platform-backup sh /backup.sh
```

## Off-host copy (Google Drive)

`/opt/radiologyos/offsite-backup-gdrive.sh` (source `infra/ops/offsite-backup-gdrive.sh`)
runs from host cron at 03:30 local, after the platform dump. It uses the owner's
Drive, the same `gdrive:` rclone remote as the OET backup, under
`radiologyos-backups/` (owner decision 2026-09-26).

- `db/<YYYYMMDD>/radiologyos.dump` and `keycloak.dump`: checked against the
  platform `MANIFEST.sha256`, uploaded, and md5-verified on Drive before any
  pruning. The newest 14 days are kept.
- `objects/current/`: an `rclone sync` mirror of the `radiologyos` MinIO bucket
  (originals, page images, figures). Throttled to 8 MB/s at low CPU/IO priority.
- `objects/deleted/<YYYYMMDD>/`: objects that left the bucket that day, kept 30
  days, so an accidental or retention delete stays recoverable for a month.
- Log: `/var/log/radiologyos-offsite-backup.log`. Last success timestamp:
  `/opt/radiologyos/offsite-backup.last-success`. Alert if it is over 26 h old.
- Restore: `rclone copy gdrive:radiologyos-backups/db/<day>/radiologyos.dump .`,
  then follow "Restoring for real". For objects, run
  `rclone copy gdrive:radiologyos-backups/objects/current radminio:radiologyos`,
  with the MinIO env from the script.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Drill reports no dump | the database was created after the last run | `docker exec platform-backup sh /backup.sh` |
| Backup aborted with no output | disk fell below the 15 GB floor | free space; the guard is deliberate |
| `pg_restore` complains about existing objects | `--clean` needs a terminated connection list | terminate backends first, as above |
| Off-host log shows `ERROR` | Drive auth expired or dump missing | `rclone about gdrive:`; re-run the script by hand |
| Checksum mismatch | truncated or corrupted dump | treat as a restore failure; do not retry against it |
| Restored database is missing RLS | wrong dump, or restored to the wrong database | re-run the drill to compare |
| Drill fails `restored alembic head = expected` | a migration was deployed after the newest dump | take a fresh dump, then re-run |

## Escalation

A checksum failure or a drill that cannot resolve its citations is a data-integrity
incident. Stop, preserve the dump, and do not prune older nights until the cause
is known — per the platform backup policy, database dumps are the only copy and
must not be deleted on the reasoning that the code is in Git.

## Known limitations

- **Off-host copy relies on the shared `gdrive:` remote.** It uses rclone's
  shared Google client id, which Google is retiring during 2026; give the
  remote its own client id before then, or the upload starts failing.
- **Off-host dumps are not client-side encrypted.** They sit in the owner's
  private Drive (encrypted at rest by Google, owner-only access).
- **Redis is not backed up.** Only durable state is expected to live there.
- Retention is seven nights, so the recovery window for a bad write is limited.
