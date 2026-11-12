"""What the game page's response headers need for GoatCounter visitor
counting (docs/plans/active/ANALYTICS_PLAN.md). The snippet itself is
in templates/party.html, and everything it's allowed to send is
decided in frontend/src/analytics.ts.

All of it is off when settings.goatcounter_site_code is empty, which
is the default: no script tag, and a Content-Security-Policy that
still allows nothing but this app's own origin.
"""

from __future__ import annotations

#: Where GoatCounter's count.js is served from.
GOATCOUNTER_SCRIPT_ORIGIN = "https://gc.zgo.at"

#: A full URL of this site's own pages (a room link, say) is never sent
#: to another site as the referrer -- only the origin is. Browsers
#: default to this already; set explicitly so it doesn't depend on
#: that. Same-origin requests still get the full URL, which is why
#: frontend/src/analytics.ts drops same-origin referrers itself.
REFERRER_POLICY = "strict-origin-when-cross-origin"


def goatcounter_origin(site_code: str) -> str:
    """Where a site's count requests go."""
    return f"https://{site_code}.goatcounter.com"


def csp_with_analytics(csp: str, site_code: str) -> str:
    """Adds to `csp` only what the snippet needs: count.js itself, and
    the count request it sends with navigator.sendBeacon (which
    connect-src governs). Nothing else is loosened -- in particular
    img-src isn't, so count.js's image fallback for browsers without
    sendBeacon stays blocked. Returns `csp` unchanged when analytics is
    off.
    """
    if not site_code:
        return csp
    with_script = _append_source(csp, "script-src", GOATCOUNTER_SCRIPT_ORIGIN)
    return _append_source(with_script, "connect-src", goatcounter_origin(site_code))


def _append_source(csp: str, directive: str, source: str) -> str:
    directives = [part.strip() for part in csp.split(";")]
    if not any(part.split(" ", 1)[0] == directive for part in directives):
        # Adding the directive here would silently override default-src
        # for it; a policy without one isn't the one this was written for.
        raise ValueError(f"Content-Security-Policy has no {directive} directive to extend")
    return "; ".join(
        f"{part} {source}" if part.split(" ", 1)[0] == directive else part for part in directives
    )
