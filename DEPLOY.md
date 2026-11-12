# Deploying Typing Twin Party to DigitalOcean App Platform

This deploys the app in **public mode** (`ENABLE_ACCOUNTS=false`): Typing
Twin Party at the app's URL, no database, no account system. See
[`docs/plans/done/PARTY_LAUNCH_PLAN.md`](docs/plans/done/PARTY_LAUNCH_PLAN.md) for the full design and
[`.do/app.yaml`](.do/app.yaml) for the exact spec these steps create.

Nothing in this repository creates a DigitalOcean resource, spends money,
or pushes anything by itself -- every step below is something you run
yourself, with your own DigitalOcean account.

## Expected cost

**$5.00/month** for the app itself, billed by the second: one
`apps-s-1vcpu-0.5gb` instance (1 shared vCPU, 512 MiB, the current
smallest paid App Platform tier), plus a few seconds of pre-deploy
job runtime per deploy (negligible). Confirmed against DigitalOcean's
own pricing page as of this writing -- re-check
<https://docs.digitalocean.com/products/app-platform/details/pricing/>
before deploying, since prices can change.

**+$0/month if you skip score collection** (`SCORES_DATABASE_URL`
unset -- see "Score database setup" below); **+$0/month on Neon's
free tier** if you turn it on, as long as usage stays inside that
tier's limits.

## Why the control panel, not `doctl`, for creating the app and its secrets

Everything below that creates the app, connects GitHub, or sets a
`SECRET`-type value (`SESSION_SECRET`, `SCORES_DATABASE_URL`) uses the
DigitalOcean **control panel**, not `doctl`. This isn't a style
preference:

- DigitalOcean's own app-spec reference documents that a `SECRET`-type
  env's value is encrypted on first submission, and "on following
  submissions, the encrypted value should be used" -- implying, but
  never actually stating, what happens if a later submission omits
  it.
- In practice, deploying this exact app, resubmitting the live spec
  with that encrypted value copied back in unmodified (exactly what
  the docs describe doing) **did not reliably work**: `doctl apps
  update` submissions that included it produced a running container
  with an empty `SESSION_SECRET` anyway, auto-rolled-back by
  DigitalOcean after failing health checks. Nothing in DigitalOcean's
  documentation (the app-spec reference, `doctl apps update`'s own
  reference page, or the control panel's spec-editor how-to) confirms
  the CLI/spec-resubmission flow is safe for this, so this guide
  doesn't recommend it.
- What did reliably work, confirmed live on this app: `doctl apps
  create-deployment <app-id>` for a plain redeploy with no spec
  involved at all, and editing a secret's value directly in the
  control panel's own Environment Variables UI (a targeted field
  edit, never a full-spec resubmission).

`doctl` is still useful, and used below, for things that don't touch
secrets: validating the spec file's shape locally
(`apps spec validate --schema-only`, no account needed) and
redeploying with `create-deployment`.

## One-time setup

1. [Create a personal access token](https://docs.digitalocean.com/reference/api/create-personal-access-token/)
   in the DigitalOcean control panel, with read/write access -- needed
   for `doctl auth init` below, and for the rollback API call later in
   this doc.

2. Install `doctl`, the DigitalOcean CLI (skip if you already have it):

   ```bash
   brew install doctl          # macOS
   # or see https://docs.digitalocean.com/reference/doctl/how-to/install/
   ```

3. Authenticate `doctl` with the token from step 1:

   ```bash
   doctl auth init
   ```

4. Validate the committed spec's shape before using it as a
   reference (no account needed for this one):

   ```bash
   doctl apps spec validate .do/app.yaml --schema-only
   ```

## First deploy

`ALLOWED_ORIGIN` and `PUBLIC_BASE_URL` must be this app's own live URL,
but DigitalOcean doesn't assign that URL (`<something>.ondigitalocean.app`)
until the app exists -- so the committed `.do/app.yaml` already has
this app's *real*, already-assigned URL in it (see "What's already
deployed" below). If you're standing this app up fresh under your own
account instead, the two-step bootstrap this section used to describe
still applies: create the app with those two values temporarily set to
`https://REPLACE_ME.ondigitalocean.app` (`config.py`'s own startup
check refuses to start with that placeholder left in -- expected,
until you've done step 4 below), note the real URL DigitalOcean
assigns, then come back and set the real values the same way you'd
change any other app-level environment variable.

1. In the control panel, **Create** → **Apps** → **GitHub** as the
   source → select this repo and the `master` branch → leave
   **Autodeploy** checked (matches `.do/app.yaml`'s own
   `deploy_on_push: true`). The first time you connect a repo,
   DigitalOcean asks to install its GitHub App on your account/repo
   -- follow that prompt.

2. On the resource-settings screen, use `.do/app.yaml`'s own values
   for anything the wizard doesn't already detect correctly from the
   Dockerfile: instance size `apps-s-1vcpu-0.5gb`, HTTP port `8000`,
   health check path `/health`.

3. Add the **app-level environment variables** from `.do/app.yaml`:
   `DEBUG=false`, `ENABLE_ACCOUNTS=false`, `ALLOWED_ORIGIN` and
   `PUBLIC_BASE_URL` (the real URL if you already know it, or the
   `REPLACE_ME` placeholder for a brand-new app), and `SESSION_SECRET`
   -- mark this one **Encrypted** in the UI and generate a real value:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Leave `SCORES_DATABASE_URL` out entirely for now if you haven't
   done "Score database setup" yet -- score collection stays off
   until it's set, and the game works normally either way.

   The wizard creates only the `web` service. The `scores-migration`
   pre-deploy job in `.do/app.yaml` is **not** created here -- "Score
   database setup" below adds it, and the app deploys fine without it.

4. Click **Create App**. For a brand-new app, once it's live, copy
   its assigned `https://<something>.ondigitalocean.app` URL (control
   panel: the app's overview page, under its name) and update
   `ALLOWED_ORIGIN`/`PUBLIC_BASE_URL` to that real value the same way
   (Settings → the `web` component → Environment Variables → edit
   each one in place), which triggers a redeploy. Confirm:

   ```bash
   curl https://<your-app>.ondigitalocean.app/health
   ```

5. Once it's healthy, update the **committed** `.do/app.yaml` to match
   (the two real URL values -- never a `SECRET`-type line, which must
   stay valueless in the repo) and open a normal PR, so the repo and
   the live app agree. This is safe to commit: the hostname isn't a
   secret, just specific to your deployment.

### What's already deployed

The committed `.do/app.yaml` already has this app's real, live URL
(`https://typing-twin-party-t9ilf.ondigitalocean.app`) -- the
bootstrap above already happened once; you'd only repeat it standing
up a separate instance of this app under a different account.

## Post-deploy checks

Run these by hand after every deploy that could affect them (a new
release, or after "Score database setup"/"Turning score collection
off again" below).

### Rate-limit identity can't be spoofed

`scripts/check_live_rate_limit.sh` floods `POST /api/game/party` with
a different fake `Do-Connecting-Ip`, then a different fake
`X-Forwarded-For`, on every request, and checks whether the app's rate
limiter was fooled into treating each one as a separate client (see
the script's own header comment, and `api/security.py`'s
`client_ip()`, for why only the first should be possible to spoof,
and only off this platform).

```bash
scripts/check_live_rate_limit.sh https://typingtwin.com
```

Expect **PASS** on both checks against the live site -- App Platform's
own ingress overwrites any `Do-Connecting-Ip` a client sends, so both
headers end up ignored for rate-limit bucketing. Run it against a
local container (`http://127.0.0.1:8000`, matching that container's
own `ALLOWED_ORIGIN`) and the `Do-Connecting-Ip` check is *expected*
to **FAIL** there instead: with no App Platform ingress in front to
overwrite the header, the local app trusts whatever value is sent, by
design (that's exactly the fallback `client_ip()`'s docstring
describes for "any host other than DigitalOcean App Platform"). A
FAIL against the live site, not just locally, means something is
wrong -- not a routine difference.

### Live updates reach the browser

Rooms update live through a server-sent event stream,
`GET /api/game/room/events` (`docs/plans/active/ROOMS_PLAN.md` Phase 2).
DigitalOcean's documentation says its edge cache must be off for a
stream like this to work over `GET`
([How to Configure Edge Settings](https://docs.digitalocean.com/products/app-platform/how-to/configure-edge-settings/),
checked 2026-11-09). That is a setting on the app, not something this
repository's code can change: in the control panel, **Networking** >
**Advanced networking and security** > **Edge caching** > **Off**. The
app already sends the two headers that page asks for
(`Content-Type: text/event-stream` and `Cache-Control: no-cache`).

```bash
scripts/check_live_events.sh https://typingtwin.com
```

It creates one room, changes it every 30 seconds for 5 minutes, and
expects **PASS** on all three lines: every change arrived on the
stream within 2 seconds, the one connection stayed open, and ending
the room closed it. It prints the stream's response headers either
way.

A FAIL doesn't break the game. A browser whose stream is silent or
refused falls back to asking for the room every 5 seconds
(`frontend/src/live.ts`), so rooms still update, just more slowly.

### If score collection is on: an attempt is stored, and Delete me removes it

Matches `docs/plans/done/PARTY_LAUNCH_PLAN.md`'s own Done-when checklist:

1. On the live site, start a party, add yourself, and make one
   attack attempt. Scores are saved automatically, so there is
   nothing to tick.
2. Confirm the row landed, using the **read-only** role (see "Running
   the analysis" below):
   ```bash
   uv run python -m evaluation.analyze_scores "<read-only connection string>"
   ```
   or a direct `SELECT count(*) FROM score_attempts WHERE created_on = current_date;`
   from Neon's SQL Editor.
3. Click **Delete me** for that player, then re-run the same count
   and confirm it dropped -- deletion matches on `party_id`/
   `typist_id`, both the random score IDs, never a name or session.

## Updating a secret without erasing it

Whenever `SESSION_SECRET` or `SCORES_DATABASE_URL` needs a new value
-- rotating one, or turning score collection on or off by setting or
clearing `SCORES_DATABASE_URL` -- edit it directly in the control
panel: the app → Settings → the `web` component (or the
`scores-migration` job, for its own copy of `SCORES_DATABASE_URL`) →
Environment Variables → edit that one entry in place. This is the
*only* path this guide recommends for a secret -- see "Why the control
panel, not `doctl`" above for why a submitted spec (via `doctl` or the
control panel's own raw spec editor) isn't. Saving triggers a redeploy
on its own; if it doesn't, `doctl apps create-deployment <app-id>`
redeploys the already-stored spec with no spec file involved at all.

A fresh `SESSION_SECRET` is fine to use if you ever need to -- it only
invalidates existing sessions, and in party mode a session is just
which party a browser belongs to, nothing worth preserving across a
redeploy.

**Every other change** -- a new domain, a different instance size,
anything that isn't a secret's value -- fetch the live spec first,
edit that, submit that; never submit the repo's `.do/app.yaml`
straight to `apps update` once the app exists with secrets already
set (it has no value for either `SECRET`-type env, and `apps update`
treats a submitted spec as the complete, authoritative state):

```bash
doctl apps spec get <app-id> --show > /tmp/live-spec.yaml
# edit /tmp/live-spec.yaml -- never the SESSION_SECRET/SCORES_DATABASE_URL
# lines' values, which arrive here already as EV[1:...] -- leave those alone
doctl apps update <app-id> --spec /tmp/live-spec.yaml
```

## Score database setup

Optional (`docs/plans/done/PARTY_LAUNCH_PLAN.md` section 10). Skip this whole section
to keep score collection off -- leave `SCORES_DATABASE_URL` unset on
the `web` service (and on the `scores-migration` job, if it exists),
and the game works exactly as it does today, saving no scores and
showing no score-saving note.

### Create the Neon project and its roles

1. [Create a Neon project](https://neon.com/docs/manage/projects)
   (free tier). Note the database name Neon creates by default.

2. Three roles are involved. Neon's default role (the database
   owner, e.g. `neondb_owner`) is the **migration** role -- it
   creates and owns the table. Create the other two yourself:
   - an **app** role -- the one `SCORES_DATABASE_URL` on the `web`
     service actually uses
   - a **read-only** role -- for `evaluation/analyze_scores.py`, run
     by hand, never by the app

   Create both **with SQL, from the Neon console's SQL Editor** --
   not with **Roles → Add role**, the Neon CLI, or the API. Neon
   makes every role created those ways a member of `neon_superuser`,
   which can read and write all data, so the grants in step 6 would
   restrict nothing. A role created with SQL starts with no access
   to the table (see <https://neon.com/docs/manage/roles>):

   ```sql
   CREATE ROLE <app_role> LOGIN PASSWORD '<password>';
   CREATE ROLE <readonly_role> LOGIN PASSWORD '<password>';
   ```

   Neon rejects weak passwords (it requires 60 bits of entropy).
   Generate each one, and never reuse one across roles:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(24))"
   ```

3. Build each role's connection string. **Connect** in the Neon
   console shows the default role's string; for the two SQL-created
   roles, take the same string and swap in that role's name and
   password. Two changes to what Neon shows, for every role:
   - Change the prefix from `postgresql://` to
     `postgresql+psycopg://`. The app, the migration job, and
     `evaluation/analyze_scores.py` all hand the string to
     SQLAlchemy, which treats a plain `postgresql://` as psycopg2 --
     not installed here (this project uses psycopg 3) -- and fails
     with `ModuleNotFoundError: No module named 'psycopg2'`.
   - For the **migration** role, use the direct connection string
     (turn **Connection pooling** off in the Connect dialog). The
     pooled string is fine for the app role.

   The result looks like
   `postgresql+psycopg://role:password@<host>/<dbname>?sslmode=require`.

### Add the migration job and run it once

4. Create the `scores-migration` job, if the app doesn't have one yet
   (check the app's **Settings** tab for a component with that name).
   This uses the control panel so no spec is resubmitted -- see "Why
   the control panel, not `doctl`" above. The values match
   `.do/app.yaml`'s own `jobs:` entry:

   1. Open the app → **Add components** → **Create resources from
      source code**.
   2. Select this repo and the `master` branch → **Next**.
   3. Under **Info**, click **Edit**, set **Resource type** to
      **Job**, and name it `scores-migration`.
   4. Under **Job trigger**, click **Edit** and choose **Before every
      deploy**.
   5. Under **Deployment settings**, click **Edit** next to the run
      command and paste this as one line. Nothing is run on your own
      machine -- DigitalOcean runs it before each deploy:

      ```
      sh -c 'if [ -z "$SCORES_DATABASE_URL" ]; then echo "SCORES_DATABASE_URL not set, skipping score migrations"; else alembic -c alembic_scores.ini upgrade head; fi'
      ```

   6. Set the instance size to `apps-s-1vcpu-0.5gb`.
   7. Add the environment variable `SCORES_DATABASE_URL`, marked
      **Encrypted**, set to the **migration** role's connection
      string from step 3 -- never the app role's, which lacks the
      privileges to create or alter a table at all.
   8. Click **Add resources**. This triggers a deploy.

   If the job already exists, set that variable on it instead
   (Settings → the `scores-migration` component → Environment
   Variables → **Encrypted**) and save.

5. Confirm the job ran `alembic -c alembic_scores.ini upgrade head`
   with no errors, in that job's own logs (`doctl apps logs <app-id>
   scores-migration --type run`, or the control panel's Activity tab
   for that deployment). `score_attempts` now exists. The `web`
   service still has no `SCORES_DATABASE_URL`, so collection is
   still off.

### Grant the two roles their access

6. In Neon's SQL Editor (which runs as the default role, the table's
   owner), grant the app role exactly what
   `docs/plans/done/PARTY_LAUNCH_PLAN.md` section 10 specifies --
   insert and delete, nothing else, confirmed against a real Postgres
   role by `tests/scores/test_db_role.py` (including the one
   non-obvious wrinkle: a `DELETE ... WHERE` needs `SELECT` on the
   columns the `WHERE` references, since Postgres has to evaluate the
   filter -- this app's own deletes filter only by `party_id`,
   `typist_id`, `target_id`, and `created_on`, so that's exactly what
   gets granted, nothing else):

   ```sql
   GRANT CONNECT ON DATABASE <dbname> TO <app_role>;
   GRANT USAGE ON SCHEMA public TO <app_role>;
   GRANT INSERT, DELETE ON score_attempts TO <app_role>;
   GRANT SELECT (party_id, typist_id, target_id, created_on)
     ON score_attempts TO <app_role>;
   ```

   And for the read-only role:

   ```sql
   GRANT CONNECT ON DATABASE <dbname> TO <readonly_role>;
   GRANT USAGE ON SCHEMA public TO <readonly_role>;
   GRANT SELECT ON score_attempts TO <readonly_role>;
   ```

### Turn collection on

7. On the `web` service, set `SCORES_DATABASE_URL` (Settings → the
   `web` component → Environment Variables → **Encrypted**) to the
   **app** role's connection string from step 3 -- a different value
   from the job's. Saving triggers a deploy.

8. Confirm collection is actually on: open the live site and check
   that the score-saving note ("This site saves a few numbers about
   each result...") appears under the name form when adding a player (it's
   PartyView's own `scores_enabled` field driving this -- see
   `GET /api/game/party` in a browser's own network tab for the raw
   response if you want to check it directly instead).

### Later score migrations

The `scores-migration` job runs `alembic -c alembic_scores.ini upgrade
head` before every deploy, so a new file in `migrations_scores/versions/`
is applied on the deploy that ships it. Nothing is run by hand.

`9d5b3e6a2c81` (touch rooms, `docs/plans/active/MOBILE_PLAN.md` Phase 1)
widens two `CHECK` constraints so `line_id` may be `touch` and `mode` may
be `grip`, and adds a nullable `screen_size` column that holds one of four
size buckets for touch rows:

- It needs the table's owner. The migration role is the owner (step 2), so
  the job's existing `SCORES_DATABASE_URL` is enough.
- No grant changes. The app role's `INSERT` and `DELETE` are on the table,
  not on particular values, so it can write touch rows as soon as the
  migration has run (`tests/scores/test_migrations.py` checks this against
  a real restricted role).
- Existing rows are kept and untouched, with an empty `screen_size`.
  Postgres rechecks them against the wider constraints under a lock that
  briefly blocks writes; a blocked insert just waits in the app's
  background writer.
- The job runs before the new code starts, so the constraints are already
  wide when the first touch room is created. If the job is missing or its
  `SCORES_DATABASE_URL` is unset, the game still plays normally, but every
  score row is refused, keyboard rows included, because the new code
  writes `screen_size` on all of them and the column isn't there. The
  refusals show as errors in the `web` logs, and "Delete me" requests that
  share a batch with a refused row are lost with it. Check that
  the job ran (step 5) before sharing a touch room.
- Rolling the app back to an older version needs no database change: the
  old code only writes values the wider constraints still allow, and
  leaves `screen_size` empty. Don't run
  `alembic downgrade` for this revision once touch rows exist. It refuses,
  and changes nothing, because the narrower constraints can't hold them.

### Running the analysis

`evaluation/analyze_scores.py` is run by hand, from your own machine,
with the **read-only** role's connection string -- never from the app,
and never with the app role's (which can't `SELECT` anything useful
anyway):

```bash
uv run python -m evaluation.analyze_scores "<read-only connection string>"
```

The string needs the `postgresql+psycopg://` prefix here too (step 3).

See `evaluation/README.md` for what it prints and its own caveats.

### Turning score collection off again

Clear `SCORES_DATABASE_URL` on the `web` service (control panel,
same place you set it) and save. The game goes back to saving no
scores and showing no score-saving note, same as before this section. The `scores-migration`
job's own `SCORES_DATABASE_URL` can stay set either way -- it only
ever runs `upgrade head`, which is a no-op once the table already
exists, and skips cleanly if it's ever unset instead.

## Visitor counting

The game page loads GoatCounter's script only when
`GOATCOUNTER_SITE_CODE` is set on the `web` component. It's a plain
value, not a secret: the site code is the `example` in
`example.goatcounter.com`, and it's visible in the page source.

To turn it on, add `GOATCOUNTER_SITE_CODE` in the control panel (the
app → Settings → the `web` component → Environment Variables), with
the same value as `.do/app.yaml`. Saving redeploys. Merging the code
alone doesn't start counting, because a push deploys the code but not
this file's environment values.

To turn it off, delete the variable or set it to an empty value. The
script tag and the two extra Content-Security-Policy sources go with
it.

After turning it on:

1. Open the site in a private window and check the visit appears in
   the GoatCounter dashboard within a minute.
2. Open any `/r/<code>` link and check the dashboard shows `/r/*`,
   never a code.
3. Check the browser console shows no Content-Security-Policy errors.

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
   (see "Updating a secret without erasing it" above: the repo's own
   file has no value for either `SECRET`-type env, and submitting it
   straight to `apps update` would clear them):

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
   Leave `SESSION_SECRET`'s and `SCORES_DATABASE_URL`'s `value:
   EV[1:...]` lines untouched -- both arrive in the fetched spec
   already encrypted; this edit never needs to touch either.

4. `doctl apps update <app-id> --spec /tmp/live-spec.yaml`, then once
   it's healthy, update the **committed** `.do/app.yaml` to match (the
   `domains:` block and the two URL values, never a `SECRET`-type
   line) and open a normal PR.

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
URL, leave both `SECRET`-type envs untouched, then `apps update` with
that edited file -- never the repo's `.do/app.yaml` directly.

## Verifying a deploy without spending anything

Everything above costs money the moment the app is actually created.
To check the app itself behaves correctly first, run it locally the
same way it'll run in production -- see the Part 1/Part 2 verification
this plan already did: a container built from the same `Dockerfile`,
capped at 512 MiB, `DEBUG=false`, `ENABLE_ACCOUNTS=false`, real-looking
`SESSION_SECRET`/`ALLOWED_ORIGIN`/`PUBLIC_BASE_URL`, and a local HTTPS
reverse proxy in front (so `X-Forwarded-Proto`/`X-Forwarded-For` are
real, not just asserted) -- run it once with `SCORES_DATABASE_URL`
unset and once with it pointed at a real (even a free local or Neon)
Postgres, since Part 2's own Done-when requires a full game to work
both ways. That's exactly what was verified by hand for this plan's
own Done-when checks, with no DigitalOcean account involved.
