# Production deployment template

The GitHub workflow deploy job is disabled unless repository variable
`DEPLOY_ENABLED` equals `true`. Before enabling it:

1. Install Docker Engine and Compose v2 on the supplied Azure VM.
2. Point the VM's DNS name at it and allow inbound TCP 22/80/443 and UDP 443.
3. Create `~/zonix-deploy/.env` from `.env.production.example`, replacing every
   placeholder. Never upload or overwrite this file from CI.
4. Add repository variables `SSH_HOST`, `SSH_USER`, `GHCR_USERNAME`, and
   `PUBLIC_BASE_URL`. The public value must be the certificate-valid HTTPS
   origin, such as `https://zonix.example.com`; it is intentionally separate
   from the SSH hostname or IP and its hostname must match `DOMAIN` in the
   VM's `.env` file.
5. Add secrets `SSH_PRIVATE_KEY` and `GHCR_READ_TOKEN`. The token needs only
   `read:packages`. The workflow trusts the VM's SSH host key on first
   connect each run (`StrictHostKeyChecking accept-new`) rather than pinning
   it via a verified secret — a deliberate simplicity trade-off for this
   project, not a hardened setup.
6. Use a protected GitHub `production` environment and protect `main` with the
   Backend tests, Frontend checks, and Container builds checks.

On each push to `main`, after CI succeeds, immutable commit-tagged images are
pushed to GHCR. The gated deploy job logs the VM into GHCR, uploads only the
versioned deployment files, applies Alembic migrations, recreates services,
and verifies `$PUBLIC_BASE_URL/api/db-health` from the runner.

The VM is not configured by this repository. Until the variables, secrets,
environment protection, DNS, and external uptime alert are configured, this is
a reviewed deployment template—not a claim that Zonix is publicly deployed.

`BACKEND_WORKERS` must remain `1` while notification fanout and upload jobs are
process-local. Scaling API workers/replicas first requires Redis (or another
shared pub/sub and durable queue) plus shared object storage.

Attachments live in the Docker named volume `zonix-production_uploads_data`.
Back up both PostgreSQL and this volume together; database rows without the
matching volume files are broken attachments. Test restore procedures before
accepting user uploads. A production object store is the preferred next step.
