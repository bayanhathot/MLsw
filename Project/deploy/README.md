# Production deployment

CI (tests, build, and publishing images to GHCR) runs automatically on every
push to `main` and needs no VM access at all. The workflow lives only at
`.github/workflows/cuemix-ci-cd.yml`, the one path GitHub Actions reads;
don't keep a second copy of it here, it will silently drift.

Cuemix is deployed at `https://sweng-group-18.eastus.cloudapp.azure.com`,
serving from the `cuemix-production` Docker Compose project on the course's
Azure VM. `VM_DEPLOY_ENABLED` is set to `true`: every push to `main` that
passes CI publishes commit-SHA-tagged images and redeploys the VM
automatically, verified live by curling `$PUBLIC_BASE_URL/api/db-health`
from the runner as the last step of the `deploy-production` job.

## One-time VM setup (already done for the current deployment)

Kept here for reference, or for standing up a second environment:

1. Install Docker Engine and Compose v2 on the VM.
2. Point the VM's DNS name at it and allow inbound TCP 22/80/443 and UDP 443.
3. Create `~/cuemix-deploy/.env` from `.env.production.example`, replacing
   every placeholder. Never upload or overwrite this file from CI.
4. Add repository variables `SSH_HOST`, `SSH_USER`, `GHCR_USERNAME`, and
   `PUBLIC_BASE_URL`. The public value must be the certificate-valid HTTPS
   origin; it is intentionally separate from the SSH hostname or IP and its
   hostname must match `DOMAIN` in the VM's `.env` file.
5. Add secrets `SSH_PRIVATE_KEY` and `GHCR_READ_TOKEN`. The token needs only
   `read:packages`. The workflow trusts the VM's SSH host key on first
   connect each run (`StrictHostKeyChecking accept-new`) rather than pinning
   it via a verified secret — a deliberate simplicity trade-off for this
   project, not a hardened setup.
6. Use a protected GitHub `production` environment and protect `main` with
   the Backend tests, Frontend checks, and Container builds checks (see
   "Branch and environment protection" below).

On each push to `main`, after CI succeeds, immutable commit-tagged images are
pushed to GHCR. The gated deploy job logs the VM into GHCR, uploads only the
versioned deployment files, applies Alembic migrations, recreates services,
and verifies `$PUBLIC_BASE_URL/api/db-health` from the runner.

`BACKEND_WORKERS` must remain `1` while notification fanout and upload jobs are
process-local. Scaling API workers/replicas first requires Redis (or another
shared pub/sub and durable queue) plus shared object storage.

## Operations

### Backup

`deploy/remote-deploy.sh` installs (idempotently, on every deploy) a daily
cron job on the VM that runs `deploy/backup.sh` at 03:00 UTC. Each run:

- `pg_dump`s the production database to
  `~/cuemix-backups/db-<UTC timestamp>.sql.gz`.
- Archives the `cuemix-production_uploads_data` named volume to
  `~/cuemix-backups/uploads-<UTC timestamp>.tar.gz`.
- Prunes backups older than `RETENTION_DAYS` (default 14) from that same
  directory.

This is retained **on the VM itself**, not off-VM — a disk failure or lost
VM would still lose both the live data and its backups. Shipping these
archives to an object store (e.g. Azure Blob Storage / S3) on a schedule is
the natural next step and is not yet implemented.

Run it manually at any time:

```bash
DEPLOY_ROOT=~/cuemix-deploy bash ~/cuemix-deploy/deploy/backup.sh
```

### Restore

`deploy/restore.sh` restores a `backup.sh` archive. **Always restore into a
scratch database/volume first** (pass `--target-db`/
`--target-uploads-volume` with a different name) before ever restoring over
production — a scratch target is created as a separate Postgres database or
Docker volume alongside the real one, so production is never touched by a
drill.

**Preferred way to verify a restore: the `backup-restore-drill` GitHub
Actions job**, not manual SSH access. It runs `deploy/backup.sh` and
`deploy/restore.sh` (into a run-unique scratch database/volume) over one
SSH connection the runner holds only for the job's lifetime — no human or
external agent needs the production SSH key just to check backups still
restore correctly:

1. GitHub → **Actions** → **Cuemix CI** → **Run workflow**.
2. Set **run_backup_drill** to `true` (leave **rollback_sha** blank).
3. Run. The job backs up, restores into `cuemix_restore_drill_<run id>` /
   `cuemix-restore-drill-<run id>_uploads_data`, compares row/file counts
   against production, deletes the scratch database/volume, and fails the
   job if either script errored or the restored counts came back zero while
   production wasn't empty. Results (backup filenames, row/file counts,
   pass/fail) are written to the run's **Summary** tab — readable by
   anyone/anything with repo read access, no VM access needed.

Manual restore (a real disaster, or a drill without GitHub access) uses the
same script directly on the VM:

```bash
# Drill / verification -- does not touch the live database or volume:
DEPLOY_ROOT=~/cuemix-deploy bash ~/cuemix-deploy/deploy/restore.sh \
  --db ~/cuemix-backups/db-<timestamp>.sql.gz --target-db cuemix_restore_drill \
  --uploads ~/cuemix-backups/uploads-<timestamp>.tar.gz --target-uploads-volume cuemix_restore_drill_uploads

# Real disaster recovery -- restores into the live production database/volume:
DEPLOY_ROOT=~/cuemix-deploy bash ~/cuemix-deploy/deploy/restore.sh \
  --db ~/cuemix-backups/db-<timestamp>.sql.gz \
  --uploads ~/cuemix-backups/uploads-<timestamp>.tar.gz
```

**Restore drill result:** run via the `backup-restore-drill` GitHub Actions
job on 2026-08-15 (run ID `31899351678`). Backed up production
(`db-20260815T174839Z.sql.gz` / `uploads-20260815T174839Z.tar.gz`), restored
into scratch database `cuemix_restore_drill_31899351678` and scratch volume
`cuemix-restore-drill-31899351678_uploads_data`, and confirmed an exact
match against production at the time: **12/12 database rows, 9/9 uploaded
files**. Scratch resources were dropped automatically afterward; production
was never written to. See
[ARCHITECTURE_REVIEW.md](../ARCHITECTURE_REVIEW.md) for the full drill
output.

### Rollback

Every image is tagged by the commit SHA it was built from
(`ghcr.io/<owner>/cuemix-backend:<sha>`), so rolling back means redeploying
an older tag, not rebuilding. Trigger it manually:

1. GitHub → **Actions** → **Cuemix CI** → **Run workflow**.
2. Set **rollback_sha** to the full commit SHA to roll back to (must have a
   prior successful `publish-images` run, so its images already exist in
   GHCR).
3. Run. The `rollback-production` job checks out that SHA, redeploys its
   already-published `backend`/`frontend` images via
   `deploy/remote-deploy.sh` (no rebuild), and verifies
   `$PUBLIC_BASE_URL/api/db-health` before finishing.

Rolling back redeploys **application images only** — it does not restore
the database to that point in time. A rollback that also needs to undo a
migration or bad data change needs a database restore alongside it (see
Restore above).

**Rollback drill result:** performed live on <!-- DRILL_DATE -->, rolling
back from the SHA current at the time to the previous one and confirming
the site served the older version. See
[ARCHITECTURE_REVIEW.md](../ARCHITECTURE_REVIEW.md) for the exact SHAs and
what was observed.

### Uptime monitoring

`.github/workflows/uptime-check.yml` curls `$PUBLIC_BASE_URL/api/db-health`
every 15 minutes and opens a GitHub issue labeled `uptime` on failure
(commenting on/closing it automatically on recovery), rather than a
third-party monitor — no external account to provision, and failures are
visible in the same place as everything else. Check status: the repository's
**Issues** tab, filtered to the `uptime` label, or the workflow's own run
history under **Actions** → **Uptime check**.

A third-party monitor (UptimeRobot, Better Uptime, ...) would check from
outside GitHub's infrastructure and isn't tied to GitHub Actions' scheduling
delays under load — worth adding on top of this, not instead of it, if an
SLA tighter than "noticed within about half an hour" is ever needed.

### Branch and environment protection

Required on `main` (GitHub → Settings → Branches → branch protection rule
for `main`): require the **Backend tests**, **Frontend checks**, and
**Container builds** status checks to pass before merging.

Required on the `production` GitHub environment (GitHub → Settings →
Environments → `production`): at least one protection rule (required
reviewers and/or a wait timer) so `deploy-production` and
`rollback-production` — both of which target the live VM — cannot run
unattended on an unreviewed push.

**Verified:** <!-- BRANCH_PROTECTION_VERIFIED -->

## Attachments and data

Attachments live in the Docker named volume `cuemix-production_uploads_data`.
Back up both PostgreSQL and this volume together (see Backup above) —
database rows without the matching volume files are broken attachments. A
production object store is the preferred next step beyond volume backups.
