"""Phase 18 (Reflex, ADR-012): page registration only. Business logic
lives in `app/*`, plumbing in `state.py`, this file just wires routes.

`_spa_fallback_router` is Phase 19-20's fix for a real bug found live:
`reflex run --env prod --single-port` 404s on `/symbols/{symbol}` for any
value not known at build time. Root cause, confirmed by reading Reflex's
own source (`reflex.utils.exec.get_frontend_mount`) and inspecting a real
`reflex export` build's output (`.web/build/client/`): react-router's
static export already generates `__spa-fallback.html` — a bootable shell
for exactly this case (a dynamic route with no enumerable set of values
at build time) — but Reflex's built-in prod static server never serves
it; an unmatched path just gets a plain 404 from Starlette's `StaticFiles`.
This wraps the backend ASGI app (via `api_transformer`, Reflex's own
documented extension point) with one explicit route that serves that
shell for this app's one dynamic route; client-side react-router then
resolves the actual symbol once the bundle boots — exactly how the shell
is meant to be used, just wired up by hand since the built-in server
doesn't do it. Dev mode is unaffected: page navigation there goes to
Vite's own dev server, never through this backend ASGI app at all.
"""

from pathlib import Path

import reflex as rx
from reflex.utils.prerequisites import get_web_dir
from reflex_base import constants
from reflex_base.config import get_config
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Route

from frontend.pages.analyze import analyze
from frontend.pages.dashboard import dashboard
from frontend.pages.feeds import feeds
from frontend.pages.symbol_detail import symbol_detail
from frontend.state import AnalyzeState, DashboardState, FeedsState, SymbolState


def _spa_fallback_path() -> Path:
    config = get_config()
    static_dir = (get_web_dir() / constants.Dirs.STATIC / config.frontend_path.strip("/")).resolve()
    return static_dir / "__spa-fallback.html"


async def _serve_spa_fallback(request: Request) -> FileResponse:
    return FileResponse(_spa_fallback_path())


_spa_fallback_router = Starlette(
    routes=[Route("/symbols/{symbol}", _serve_spa_fallback, methods=["GET"])]
)

app = rx.App(api_transformer=_spa_fallback_router)
# on_load (registered here), not each page's own on_mount: a real bug
# found live in Phase 19-20's full docker-compose validation. on_mount is
# a component-lifecycle hook — it doesn't refire on navigating BACK to a
# route already mounted once in the same SPA session (react-router keeps
# the app shell alive across navigation), so the dashboard kept showing
# stale data after adding a symbol to monitor from another page. on_load
# is Reflex's own page-level hook, specifically documented to fire on
# every navigation TO a route, which is what "refresh this page's data
# when visited" actually needs.
app.add_page(dashboard, route="/", title="Trading Advisor", on_load=DashboardState.load)
app.add_page(symbol_detail, route="/symbols/[symbol]", title="Symbol", on_load=SymbolState.load)
# on_load also picks up `?symbol=` from a /feeds suggestion link, not just
# a plain visit — same on_load-over-on_mount reasoning as above, since a
# suggestion link re-navigates to an already-mounted /analyze route within
# the same SPA session just as often as a fresh visit.
app.add_page(analyze, route="/analyze", title="Analyze", on_load=AnalyzeState.load_from_query)
app.add_page(feeds, route="/feeds", title="Feeds", on_load=FeedsState.load)
