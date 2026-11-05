# TODO

Everything that was open before the Python 3 rewrite (SQL injection, the
file-write bug, no auth, unrestricted CORS, Python 2, hardcoded IPs, no
tests, no pinned dependencies, `keystroke.sqlite` committed, and so on) is
closed -- see the Phase 0 closeout table given alongside Phase 7's review
for the full list with what fixed each one.

What's still open:

1. **No minimum enrollment length enforced.** `/api/profile/samples`
   accepts and counts a sample with as little as one key press -- nothing
   stops a near-empty sample from being added to a profile. Each individual
   feature still needs `min_feature_count` (5) samples before scoring uses
   it, so the practical impact is limited, but there's no explicit floor.

2. **Rate limiting is keyed by `request.client.host`.** Already documented
   as in-memory/per-process in `api/rate_limit.py`; additionally, behind a
   reverse proxy or shared NAT, every client behind it shares one IP and
   therefore one rate-limit bucket -- either one bad actor blocks everyone
   behind the same address, or (if the proxy's own IP is all the app ever
   sees) the limit effectively doesn't apply per-client at all. Fine for a
   direct-to-app local deployment; would need `X-Forwarded-For` handling
   (from a trusted proxy only) for anything fronted by one.

3. **`KeyEventSchema.code` has no explicit length bound.** In practice it's
   bounded by `max_body_bytes` (the whole request), but a per-field
   `max_length` would be cheap defense in depth.

4. **`core.stats.combine()` is unused in the app.** Implements the
   parallel/batch variant of Welford's algorithm and is tested, but nothing
   in `api/`/`db/` calls it -- `save_sample_features` applies `update()`
   one event at a time instead. Keep for a future batch-enrollment path, or
   remove if none is planned.

5. **Typing Twin (`/typing-twin`) leaves orphan `users` rows, one per real
   player per party.** Each real player registers a random, disposable
   account; "New party" deletes every real player's typing profile but not
   the account itself, since there's no account-deletion endpoint (the app
   never needed one before this). The orphan rows carry no typing data once
   the profile is deleted, just a random username and a password hash
   nobody has. Fine for a demo; would need a real cleanup path (an admin
   job, or an actual DELETE /api/account) if this saw real traffic. The
   three simulated "sample" players in a party never touch the backend at
   all, so they don't add to this.

6. **Typing Twin Party's full e2e suite needs a raised `RATE_LIMIT_MAX_ATTEMPTS`
   to run locally.** The suite's cumulative login/register calls across all
   spec files legitimately exceed the production default's 10-per-60s
   budget (tuned for a real user, not an automated suite exercising several
   accounts back to back) -- see `frontend/README.md`'s End-to-end tests
   section. Not a defect in the limiter; just means `npm run e2e` needs
   `RATE_LIMIT_MAX_ATTEMPTS=50` set on the dev server it's pointed at.

See `MODERNIZATION_PLAN.md`'s "Later ideas (not part of this work)" for
BioKey's update-after-login step and other explicitly out-of-scope ideas.
