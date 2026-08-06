# Zonix Azure deployment

The GitHub Actions workflow (`.github/workflows/zonix-ci-cd.yml`) tests every
push and pull request. A pull request stops after the test jobs - it never
builds, pushes, or deploys. Only a push to `main` builds the images, pushes
them to GitHub Container Registry (GHCR), and deploys them to the Azure VM.

## The VM is provided for you

Unlike a typical deployment, you do **not** provision the Azure VM yourself.
The instructor gives your group one VM (its FQDN and public IP), already
configured with:

- A `deploy` user with **key-only** SSH access (password login is disabled).
- Inbound ports **22** (SSH), **80** (HTTP / ACME challenge), and **443**
  (HTTPS) open - no other ports are reachable.
- A DNS label, so the VM has a real FQDN like
  `<label>.<region>.cloudapp.azure.com` (this is what Caddy uses to obtain a
  Let's Encrypt certificate - a bare IP address cannot get one).

You grant the pipeline access by generating your own deploy keypair and
sending the instructor **only the public half**:

```bash
ssh-keygen -t ed25519 -C "groupNN-deploy" -f groupNN_deploy
```

(Windows PowerShell: omit `-N ""` and press Enter twice at the passphrase
prompts instead - PowerShell can silently drop an empty-string argument to a
native command.) Send `groupNN_deploy.pub` to the instructor, renamed to
`groupNN.pub`. Never send `groupNN_deploy` (no extension) - that's the private
key.

## One-time setup on the VM

SSH in once, by hand, before wiring up CI (this is not a "manual deploy step"
- it's one-time environment prep):

```bash
ssh deploy@<your-fqdn>
docker --version && docker compose version   # confirm both are present
mkdir -p ~/zonix-deploy/deploy
```

Then create `~/zonix-deploy/.env` with real values (copy
`deploy/.env.production.example` as a starting point and replace every
placeholder - a long random `POSTGRES_PASSWORD`, a long random `SECRET_KEY`
via e.g. `openssl rand -hex 32`, and `DOMAIN` set to your VM's FQDN). This
file holds real secrets, is created once by hand, and is never touched or
overwritten by the pipeline.

## GitHub repository secrets and variables

In your repo: **Settings → Secrets and variables → Actions**.

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `SSH_PRIVATE_KEY` | Full contents of `groupNN_deploy` (the private key, including the `BEGIN`/`END` lines) |
| Variable | `SSH_HOST` | Your VM's FQDN, e.g. `course-group-07.eastus.cloudapp.azure.com` |
| Variable | `SSH_USER` | `deploy` |

`SSH_PRIVATE_KEY` must be a **secret** - GitHub masks it in every log line.
`SSH_HOST`/`SSH_USER` aren't sensitive and belong under **Variables**, not
Secrets.

No registry credentials are needed for **pushing**: that uses the
automatically provided `GITHUB_TOKEN`, scoped to `packages: write` only for
the `build-and-push` job.

**One required one-time step:** GHCR packages pushed via `GITHUB_TOKEN`
default to **private**. The VM has no GHCR credential of its own (the
assignment's secret set is deliberately minimal - just the three above), so
`docker compose pull` on the VM only works if the packages are public. After
the *first* successful push to `main` creates the `zonix-backend` and
`zonix-frontend` packages, go to each package's page (your GitHub profile/org
→ **Packages**) → **Package settings** → **Change visibility** → **Public**.
This is a one-time setting per package, not a per-deploy step.

## GitHub branch protection

Protect `main` and require these checks before merging:

- `Backend tests`
- `Frontend checks`

Disable direct pushes to `main`. Development should happen on branches and
reach `main` through pull requests after the tests pass.

## Deployment flow

```text
push to a branch / open a PR
  -> backend tests + migration check
  -> frontend type checks + production build
  (pull request stops here - never builds, pushes, or deploys)

push to main
  -> backend tests + frontend checks (same as above)
  -> build backend + frontend images, tag :latest and :<short-sha>
  -> push both tags to ghcr.io/<owner>/zonix-backend and zonix-frontend
  -> upload docker-compose.prod.yml + deploy/Caddyfile + deploy/remote-deploy.sh over SSH
  -> on the VM: pull the new images, run Alembic migrations, restart the stack
  -> curl the public HTTPS FQDN's /api/db-health from the runner - fail the
     run if it doesn't come back healthy
```

The VM **never builds** anything - `remote-deploy.sh` only pulls the images
that CI already built and pushed. Re-running the same commit re-pulls the
same tags and restarts the same containers, so a deploy is idempotent.

## Health check

The pipeline verifies `https://<your-fqdn>/api/db-health`, which Caddy
forwards to the backend's `GET /db-health` (it runs `SELECT 1` against
Postgres, so it verifies the whole stack is actually working, not just that
the process started). Point your external uptime monitor at the same URL.

## External uptime monitoring (not part of the pipeline)

Separately from CI, set up a third-party monitor (UptimeRobot, Better Stack,
Healthchecks.io, ...) polling `https://<your-fqdn>/api/db-health` at an
interval of 5 minutes or less, with alerting on. This has to run on
infrastructure the instructor's VM doesn't control, so it can't be part of
this repository or workflow - it's a separate account you configure once.

## Rotating a leaked key

If `groupNN_deploy` (the private key) is ever exposed - committed, pasted in
a log, shared over an insecure channel - generate a new keypair, send the
instructor the new `.pub`, update the `SSH_PRIVATE_KEY` secret, and ask the
instructor to remove the old public key from the VM's `authorized_keys`.

`BACKEND_WORKERS` controls parallel Uvicorn worker processes, set in
`~/zonix-deploy/.env`. Start with `2` on a small VM and increase it according
to available CPU and memory.
