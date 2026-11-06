# Deploying Typing Twin Party to DigitalOcean App Platform

This deploys the app in **public mode** (`ENABLE_ACCOUNTS=false`): Typing
Twin Party at the app's URL, no database, no account system. See
[`PARTY_LAUNCH_PLAN.md`](PARTY_LAUNCH_PLAN.md) for the full design and
[`.do/app.yaml`](.do/app.yaml) for the exact spec these steps create.

Nothing in this repository creates a DigitalOcean resource, spends money,
or pushes anything by itself -- every step below is something you run
yourself, with your own DigitalOcean account.

## Expected cost

**$5.00/month**, billed by the second. That's the whole bill: one
`apps-s-1vcpu-0.5gb` instance (1 shared vCPU, 512 MiB, the current
smallest paid App Platform tier), no database, no add-ons. Confirmed
against DigitalOcean's own pricing page as of this writing -- re-check
<https://docs.digitalocean.com/products/app-platform/details/pricing/>
before deploying, since prices can change.

## One-time setup

1. Install `doctl`, the DigitalOcean CLI (skip if you already have it):

   ```bash
   brew install doctl          # macOS
   # or see https://docs.digitalocean.com/reference/doctl/how-to/install/
   ```

2. [Create a personal access token](https://docs.digitalocean.com/reference/api/create-personal-access-token/)
   in the DigitalOcean control panel, with read/write access.

3. Authenticate `doctl` with it:

   ```bash
   doctl auth init
   ```

4. The app deploys from this GitHub repo on push to `master`
   (`.do/app.yaml`'s `github.deploy_on_push: true`). The first time you
   create an app from a GitHub repo, DigitalOcean asks to install its
   GitHub App on your account/repo -- the control panel flow (step 5)
   walks you through this; there's no way to pre-authorize it from the
   CLI alone.

## First deploy (two steps, because of a chicken-and-egg problem)

`ALLOWED_ORIGIN` and `PUBLIC_BASE_URL` must be this app's own live URL,
but DigitalOcean doesn't assign that URL (`<something>.ondigitalocean.app`)
until the app exists. So:

### Step 1: create the app with placeholder URLs

```bash
doctl apps create --spec .do/app.yaml
```

This prompts you to authorize GitHub access (if you haven't already) and
to enter a value for `SESSION_SECRET` (the one env var marked `type:
SECRET` with no value in the file -- never put a real secret in the
committed file). Generate one with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

The app will build and deploy, but **will crash-loop** -- `config.py`'s
own startup check refuses to start with `ALLOWED_ORIGIN`/`PUBLIC_BASE_URL`
still pointing at the placeholder `REPLACE_ME.ondigitalocean.app`. That's
expected. Note the app's ID from the command's output (or `doctl apps
list`).

### Step 2: set the real URL and redeploy

```bash
doctl apps list --format ID,DefaultIngress
```

Copy the `DefaultIngress` value (`https://typing-twin-party-xxxxx.ondigitalocean.app`).
Edit `.do/app.yaml`, replacing both `REPLACE_ME.ondigitalocean.app`
placeholders with that real hostname, then:

```bash
doctl apps update <app-id> --spec .do/app.yaml
```

The app redeploys and should come up healthy this time. Confirm:

```bash
curl https://<your-app>.ondigitalocean.app/health
```

**Do not commit** the edited `.do/app.yaml` with your real domain baked
into `ALLOWED_ORIGIN`/`PUBLIC_BASE_URL` unless you're fine with that
being public -- it's not a secret, just specific to your deployment.
(If you later attach a custom domain -- see below -- update these two
values again to match it, and redeploy.)

## Keeping CI in the loop

`.do/app.yaml` sets `deploy_on_push: true`, per the plan -- DigitalOcean
deploys automatically on every push to `master`. DigitalOcean's own
auto-deploy has no built-in "wait for GitHub Actions" option, so there's
a real choice here. Three ways to actually get it, in increasing order
of automation and setup cost:

1. **Branch protection (what this currently relies on, no extra setup).**
   Require `.github/workflows/ci.yml`'s `test` and `docker` jobs to pass
   before a PR can merge to `master`, in the repo's Settings → Branches.
   Since nothing reaches `master` without CI already green, DigitalOcean's
   auto-deploy is effectively gated too. Doesn't protect against a direct
   push to `master` that bypasses branch protection (e.g. an admin
   override) or a force-push.

2. **DigitalOcean's own GitHub Actions deploy action, CI-gated.** Set
   `deploy_on_push: false` in `.do/app.yaml`, and add a job to
   `ci.yml` using
   [`digitalocean/app_action/deploy@v2`](https://docs.digitalocean.com/products/app-platform/how-to/deploy-from-github-actions/)
   with `needs: [test, docker]`, so it only runs after both pass. Needs
   a `DIGITALOCEAN_ACCESS_TOKEN` GitHub repo secret and the app's ID.
   Fully automatic, gated, and survives a direct push to `master` -- but
   is more to set up and maintain.

3. **Fully manual.** Set `deploy_on_push: false`; after confirming CI is
   green, run `doctl apps create-deployment <app-id>` (or click **Deploy**
   in the control panel) yourself. No extra secrets, most control, no
   automation.

This repo ships with option 1 (the plan's own "auto-deploy on push"
requirement, satisfied the simplest way). Switch to option 2 if you want
deploys to survive a direct push; I didn't choose for you.

## Rolling back

**Control panel** (simplest): open the app → **Activity** tab → find the
last good deployment → click **Rollback**. The panel shows a diff of what
changes. Consider unchecking **Automatically Deploy Code Changes** in
**More Options** while you fix the cause, so the next auto-deploy doesn't
immediately undo the rollback.

**API** (no dedicated `doctl` subcommand exists for this in the version
available at the time of writing -- `doctl apps --help` lists
`create-deployment`/`list-deployments`/`get-deployment` but no
`rollback`): find the deployment ID to roll back to with
`doctl apps list-deployments <app-id>`, then:

```bash
curl -X POST \
  -H "Authorization: Bearer $DIGITALOCEAN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"deployment_id": "<deployment-id>"}' \
  "https://api.digitalocean.com/v2/apps/<app-id>/rollback"
```

## Changing the domain

1. Edit `.do/app.yaml`'s `domains:` (not present by default -- add it):

   ```yaml
   domains:
     - domain: your-domain.com
       type: PRIMARY
   ```

2. `doctl apps update <app-id> --spec .do/app.yaml`
3. Point your domain's DNS at the two public ingress IPs App Platform
   gives you (control panel → app → **Settings** → **Domains**), or a
   CNAME if you're using a subdomain.
4. **Update `ALLOWED_ORIGIN` and `PUBLIC_BASE_URL`** in the same spec to
   the new domain and redeploy (step 2 again) -- otherwise the Origin
   check (`api/security.py`) will reject every request from the new
   domain, and link previews will point at the old one.

To revert to the `*.ondigitalocean.app` domain, remove the `domains:`
block (or set its `type` back to `DEFAULT`) and update
`ALLOWED_ORIGIN`/`PUBLIC_BASE_URL` back, then redeploy.

## Verifying a deploy without spending anything

Everything above costs money the moment `doctl apps create` runs. To
check the app itself behaves correctly first, run it locally the same
way it'll run in production -- see the Part 1/Part 2 verification this
plan already did: a container built from the same `Dockerfile`, capped
at 512 MiB, `DEBUG=false`, `ENABLE_ACCOUNTS=false`, real-looking
`SESSION_SECRET`/`ALLOWED_ORIGIN`/`PUBLIC_BASE_URL`, and a local HTTPS
reverse proxy in front (so `X-Forwarded-Proto`/`X-Forwarded-For` are
real, not just asserted) -- that's exactly what was verified by hand for
this plan's own Done-when checks, with no DigitalOcean account involved.
