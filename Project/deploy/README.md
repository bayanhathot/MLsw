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

Before images can be published, the container gate builds all three Cuemix
images and starts the complete `docker-compose.prod.yml` topology with the
disposable, non-secret `deploy/system-test.env`. It checks Caddy's public HTTPS
routes, backend/database/Redis health, Studio AI health, and media delivery;
then it runs the complete browser journey and a bounded 20-user workload
through the same public edge. A failure prevents image publishing and Azure
deployment, and the disposable containers and volumes are always removed.

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
   The workflow also manages four non-secret settings. Their current
   course-test defaults match `Project/.env`:
   `AUDIUS_ANALYSIS_CACHE_ENABLED=true`, `DEBUG_DASHBOARD_ENABLED=true`,
   `ENABLE_PIPELINE_DEBUG=true` (debug mode is on everywhere right now --
   this VM isn't serving real production traffic yet), and
   `BACKEND_WORKERS=1` (see the "Backend concurrency boundary" section below).
   Define repository variables named `AUDIUS_ANALYSIS_CACHE_ENABLED`,
   `DEBUG_DASHBOARD_ENABLED`, or `ENABLE_PIPELINE_DEBUG` to override those
   feature defaults for an emergency shutdown. `BACKEND_WORKERS` is pinned to
   `1` in CI until the upload-queue limitation below is removed, so a stale
   repository variable cannot silently restore the unsafe two-process setup.
5. Add secrets `SSH_PRIVATE_KEY` and `GHCR_READ_TOKEN`. The token needs only
   `read:packages`. The workflow trusts the VM's SSH host key on first
   connect each run (`StrictHostKeyChecking accept-new`) rather than pinning
   it via a verified secret — a deliberate simplicity trade-off for this
   project, not a hardened setup.
6. Use a protected GitHub `production` environment and protect `main` with
   the Backend tests, Frontend checks, and Container builds checks (see
   "Branch and environment protection" below).

On each push to `main`, after CI succeeds, immutable commit-tagged backend,
frontend, and Studio-AI images are pushed to GHCR. The gated deploy job logs
the VM into GHCR, uploads only the
versioned deployment files, applies Alembic migrations, recreates services,
and verifies `$PUBLIC_BASE_URL/api/db-health` from the runner. Before Compose
runs, `remote-deploy.sh` synchronizes the four managed settings into
the VM's persistent `~/cuemix-deploy/.env`; after recreation it verifies each
one against the running deployment and fails on drift -- `printenv` inside
the backend container for the three boolean flags, and the container's own
launch args for `BACKEND_WORKERS` (which only ever reaches `uvicorn`'s
`--workers` argument, never the container's environment). This is necessary
because CI intentionally preserves the VM's `.env`, so a stale explicit value
would otherwise override a newer Compose default.

The same deploy script refreshes the Studio assistant's non-secret runtime
contract (`STUDIO_AI_TIMEOUT_SECONDS`, `STUDIO_AI_KEEP_ALIVE`, model timeout,
context/output limits, and temperature). This prevents an existing VM from
retaining the prototype's shorter timeout while leaving the operator-selected
`OLLAMA_MODEL` and secret `STUDIO_AI_INTERNAL_TOKEN` untouched.

The Studio AI container is internal-only and shares the production Ollama and
Redis services. Its `/ready` result requires the configured model to be present
and loaded in memory. Studio requests always enable reasoning and send
`STUDIO_AI_KEEP_ALIVE=-1`; the production keepalive sidecar also reloads the
model after a VM/container restart and is explicitly started by every deploy.
The deployment then runs `deploy/verify-local-llm.sh` on the VM. This is a hard
gate: it verifies Ollama responds, the configured model is installed and loaded,
Studio `/ready` names that model, and one real schema-validated edit plan finishes
within `STUDIO_AI_TIMEOUT_SECONDS`. Any failure stops the deployment instead of
leaving a green run with a broken local model. Runtime behavior remains fail-open:
if the model later becomes unavailable, manual Studio editing, rendering, and
publishing still work.

### Backend concurrency boundary

Production intentionally uses `BACKEND_WORKERS=1`. Upload processing is still
parallel: that one web process owns a bounded priority queue with
`UPLOAD_WORKERS=4` worker threads, so up to four media jobs can be validated
and analyzed concurrently without creating multiple independent job queues.

Realtime fanout, rate limiting, pipeline-debug invalidation, and Ollama's
concurrency semaphore/statistics are shared through Redis. UploadQueue is not
yet fully distributed, however: Redis mirrors job state for restart durability,
while the active `PriorityQueue`, `_jobs`, `_batches`, and materialization locks
remain process-local and Redis recovery runs only at process startup. With two
web processes, a status/cancel/retry request can reach a process that does not
know the job, and both processes can recover the same active job. Raising
`BACKEND_WORKERS` is therefore unsafe until Redis becomes the authoritative
dispatcher with atomic claims/leases and Redis-backed reads for every job and
batch operation.

Scaling to multiple processes or separate hosts/pods would additionally need
shared object storage (S3/MinIO or a network filesystem) for
`UPLOAD_DIR` in place of the local `uploads_data` volume, since rendered
mixes/session audio and catalog uploads are currently only visible across
workers because they share one container's mount, not because anything
storage-aware was built. `app/routers/media.py`,
`app/services/pipeline/audio_renderer.py`, `app/services/upload_queue.py`,
and `app/services/pipeline/catalog_retriever.py` would all need their direct
filesystem reads/writes routed through that abstraction instead.

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
was never written to.

### Rollback

Every image is tagged by the commit SHA it was built from
(`ghcr.io/<owner>/cuemix-backend:<sha>`), so rolling back means redeploying
an older tag, not rebuilding. Trigger it manually:

1. GitHub → **Actions** → **Cuemix CI** → **Run workflow**.
2. Set **rollback_sha** to the full commit SHA to roll back to (must have a
   prior successful `publish-images` run, so its images already exist in
   GHCR).
3. Run. The `rollback-production` job checks out that SHA, redeploys its
   already-published `backend`/`frontend`/`studio-ai-service` images via
   `deploy/remote-deploy.sh` (no rebuild), and verifies
   `$PUBLIC_BASE_URL/api/db-health` before finishing.

Rolling back redeploys **application images only** — it does not restore
the database to that point in time. A rollback that also needs to undo a
migration or bad data change needs a database restore alongside it (see
Restore above).

**Rollback drill result:** performed live on 2026-08-15, rolling back to
`10ef342609eb59cb8f374d7425203f076d9aacf8`. Confirmed via `docker ps` on
the VM that both `cuemix-production-backend-1` and
`cuemix-production-frontend-1` were running images tagged with the
rollback SHA, and the job's own health-endpoint check passed. This drill
also caught a real concurrency-group bug: a manual `workflow_dispatch` run
shared its concurrency group with ordinary push-triggered CI runs on the
same branch, so a rollback/drill dispatch could silently cancel an
in-flight push's own test/build/publish/deploy before its images ever
published (`cuemix-ci-cd.yml`'s `concurrency.group` now keys
`workflow_dispatch` runs by `run_id` instead). Production was rolled
forward again afterward to restore the latest commit.

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
reviewers and/or a wait timer) so `deploy-production`,
`rollback-production`, and `backup-restore-drill` — all three of which
touch the live VM — cannot run unattended on an unreviewed push or a
casual manual dispatch.

**Status: not yet verified.** Both of the above require repository
**Settings** access (Branches / Environments), which is admin-only —
neither this session's git identity nor an unauthenticated API call can
read or change them. **Action needed from whoever has repo-admin access**
(the repository owner): open both Settings pages above and confirm the
required checks / environment protection rule are actually in place, then
update this line to record what was found.

## Attachments and data

Attachments live in the Docker named volume `cuemix-production_uploads_data`.
Back up both PostgreSQL and this volume together (see Backup above) —
database rows without the matching volume files are broken attachments. A
production object store is the preferred next step beyond volume backups.
