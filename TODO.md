# TODO

Everything that was open before the Python 3 rewrite (SQL injection, the
file-write bug, no auth, unrestricted CORS, Python 2, hardcoded IPs, no
tests, no pinned dependencies, `keystroke.sqlite` committed, and so on) is
closed -- see the Phase 0 closeout table given alongside Phase 7's review
for the full list with what fixed each one.

What's still open:

1. **BioKey 2012 benchmark comparison not implemented.** Phase 3 was
   completed before the BioKey 2012 method section was added to
   `MODERNIZATION_PLAN.md`. `evaluation/biokey_2012.py`,
   `tests/test_biokey_2012.py`, and the updated `evaluation/results.md`
   reporting it calls for don't exist yet. Scoped as its own follow-up
   task, not redone retroactively into Phase 3.

2. **No minimum enrollment length enforced.** `/api/profile/samples`
   accepts and counts a sample with as little as one key press -- nothing
   stops a near-empty sample from being added to a profile. Each individual
   feature still needs `min_feature_count` (5) samples before scoring uses
   it, so the practical impact is limited, but there's no explicit floor.

3. **Rate limiting is keyed by `request.client.host`.** Already documented
   as in-memory/per-process in `api/rate_limit.py`; additionally, behind a
   reverse proxy or shared NAT, every client behind it shares one IP and
   therefore one rate-limit bucket -- either one bad actor blocks everyone
   behind the same address, or (if the proxy's own IP is all the app ever
   sees) the limit effectively doesn't apply per-client at all. Fine for a
   direct-to-app local deployment; would need `X-Forwarded-For` handling
   (from a trusted proxy only) for anything fronted by one.

4. **`KeyEventSchema.code` has no explicit length bound.** In practice it's
   bounded by `max_body_bytes` (the whole request), but a per-field
   `max_length` would be cheap defense in depth.

5. **`core.stats.combine()` is unused in the app.** Implements the
   parallel/batch variant of Welford's algorithm and is tested, but nothing
   in `api/`/`db/` calls it -- `save_sample_features` applies `update()`
   one event at a time instead. Keep for a future batch-enrollment path, or
   remove if none is planned.
