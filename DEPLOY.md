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

**Don't submit `.do/app.yaml` directly with `apps update` here** --
that file deliberately has no value for `SESSION_SECRET` (see step 1),
and `apps update` takes the submitted spec as the complete, authoritative
state: a `SECRET`-type env with no value **clears** the one DigitalOcean
already encrypted and stored, rather than leaving it alone. (Learned
this the hard way: the app crash-looped again, this time on a missing
`SESSION_SECRET` it had already been given.) Every update after the
first has to start from the *live* spec instead:

```bash
doctl apps spec get <app-id> --show > /tmp/live-spec.yaml
```

Edit `/tmp/live-spec.yaml` (not the repo's file), replacing both
`REPLACE_ME.ondigitalocean.app` placeholders with the real hostname.
Leave the `SESSION_SECRET` entry's `value: EV[1:...]` exactly as it
is. Then:

```bash
doctl apps update <app-id> --spec /tmp/live-spec.yaml
```

The app redeploys and should come up healthy this time (give it a
minute or two -- check with `doctl apps list-deployments <app-id>`).
Confirm:

```bash
curl https://<your-app>.ondigitalocean.app/health
```

Once it's healthy, update the **committed** `.do/app.yaml` to match
(the two real URL values -- never the `SESSION_SECRET` line, which
must stay valueless in the repo) and open a normal PR, so the repo and
the live app agree. This is safe to commit: the hostname isn't a
secret, just specific to your deployment.

**Every future change via `apps update`** -- a new domain, a different
instance size, anything -- follows this same pattern: fetch the live
spec with `--show`, edit that, submit that. Never submit the repo's
`.do/app.yaml` straight to `apps update` once the app exists with a
secret already set.

**What actually happened deploying this app, for when it happens
again:** copying the `EV[1:...]` value back in (as above) did *not*
reliably work -- several `apps update` submissions that included it
unmodified still produced a running container with an empty
`SESSION_SECRET`, each time auto-rolled-back by DigitalOcean after
failing health checks. The control panel's own "Undeployed changes:
your live deployment and app spec are out of sync" warning is a
symptom of this -- the *proposed* spec (what you're editing) and the
*active* one (what's actually running, after being auto-rolled-back)
had drifted apart. What worked:

1. **For a plain redeploy with no config change**: `doctl apps
   create-deployment <app-id>` -- re-deploys the already-stored spec
   as-is, no spec file involved at all, so there's nothing to corrupt.
2. **For an actual `SESSION_SECRET` problem**: edit it directly in the
   control panel (Settings → the `web` component → Environment
   Variables) rather than through any CLI spec file, then
   `create-deployment` if saving doesn't trigger one itself. Typing a
   fresh value in directly sidesteps whatever the CLI round-trip
   issue was. A fresh secret is fine to use -- it only invalidates
   existing sessions, and in party mode a session is just which party
   a browser belongs to, nothing worth preserving across a
   redeploy.

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

### typingtwin.com

This domain is bought and intended for this app, but **not wired up
yet** -- the steps below haven't been run. The live app is currently
still on its `*.ondigitalocean.app` domain. To switch:

1. Fetch the *live* spec -- **not** the repo's `.do/app.yaml` directly
   (see the warning in "First deploy" step 2: submitting it straight
   to `apps update` clears the already-encrypted `SESSION_SECRET`):

   ```bash
   doctl apps spec get <app-id> --show > /tmp/live-spec.yaml
   ```

2. Edit `/tmp/live-spec.yaml`: add a `domains:` key at the spec's top
   level (a sibling of `name:`/`services:`, not present by default):

   ```yaml
   domains:
     - domain: typingtwin.com
       type: PRIMARY
     - domain: www.typingtwin.com
       type: ALIAS
   ```

   (Drop the `www` alias if you don't want it -- it's optional.)

3. **Update `ALLOWED_ORIGIN` and `PUBLIC_BASE_URL`** in the same file to
   `https://typingtwin.com` (not the `www` version -- pick the one you
   set as `PRIMARY` above). Skipping this means the Origin check
   (`api/security.py`) rejects every request from the new domain, and
   link previews keep pointing at the old `.ondigitalocean.app` one.
   Leave `SESSION_SECRET`'s `value: EV[1:...]` untouched.

4. `doctl apps update <app-id> --spec /tmp/live-spec.yaml`, then once
   it's healthy, update the **committed** `.do/app.yaml` to match (the
   `domains:` block and the two URL values, never `SESSION_SECRET`)
   and open a normal PR.

5. At your domain registrar/DNS provider for `typingtwin.com`, add:

   | Type | Host | Value |
   |---|---|---|
   | A | `@` | `162.159.140.98` |
   | A | `@` | `172.66.0.96` |
   | AAAA | `@` | `2606:4700:7::60` |
   | AAAA | `@` | `2a06:98c1:58::60` |
   | CNAME | `www` | `typingtwin.com.` (or the same A/AAAA records) |

   These four IPs are DigitalOcean App Platform's shared static ingress
   addresses (confirmed current as of this writing --
   <https://docs.digitalocean.com/products/app-platform/how-to/add-ip-address/>
   covers both this and dedicated per-app IPs, if you'd rather use
   one of those instead). DNS propagation can take anywhere from
   minutes to a day depending on the registrar and your previous TTL.

6. Confirm: `curl https://typingtwin.com/health`, then a full page
   load -- DigitalOcean also auto-provisions a Let's Encrypt
   certificate for the domain once DNS resolves to it, which can take
   a few extra minutes after step 4 before HTTPS works.

### Reverting to the `*.ondigitalocean.app` domain

Same live-spec pattern as above (steps 1-4): fetch the live spec,
remove the `domains:` block (or set its `type` back to `DEFAULT`), set
`ALLOWED_ORIGIN`/`PUBLIC_BASE_URL` back to the `ondigitalocean.app`
URL, leave `SESSION_SECRET` untouched, then `apps update` with that
edited file -- never the repo's `.do/app.yaml` directly.

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
