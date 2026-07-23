"""
Serve the built SPA (spec §3.4).

mount_dashboard() must be called LAST in app/main.py: it registers a catch-all
that returns index.html for client-side routes. FastAPI matches in registration
order, so anything registered afterwards would be shadowed.

Belt and braces, the catch-all also refuses reserved prefixes outright, so a
future router added after this call still 404s honestly instead of silently
serving HTML to an API client.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from dashboard.api.auth import require_dashboard_auth

logger = logging.getLogger(__name__)

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"
INDEX_FILE = DIST_DIR / "index.html"

# Paths that belong to the bot, not the dashboard. The catch-all never answers
# for these even if no router claimed them.
RESERVED_PREFIXES: tuple[str, ...] = (
    "/webhooks",
    "/internal",
    "/health",
    "/diagnostics",
    "/api",
    "/docs",
    "/redoc",
    "/openapi.json",
)

_MISSING_BUILD_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Dashboard not built</title>
<style>body{background:#0A0C10;color:#fff;font:14px/1.6 ui-sans-serif,system-ui;
padding:48px;max-width:640px;margin:0 auto}code{background:#12161C;padding:2px 6px;
border-radius:4px;color:#86b6ef}</style></head><body>
<h1>Dashboard not built</h1>
<p>No build output found at <code>dashboard/dist</code>.</p>
<p>Build it with:</p>
<pre><code>cd dashboard/web &amp;&amp; npm ci &amp;&amp; npm run build</code></pre>
<p>See <code>dashboard/README.md</code>.</p>
</body></html>"""


def _is_reserved(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in RESERVED_PREFIXES)


def mount_dashboard(app: FastAPI) -> None:
    """Register static assets, the root redirect, and the SPA catch-all."""
    assets_dir = DIST_DIR / "assets"
    if assets_dir.is_dir():
        # Hashed filenames from Vite — safe to serve unauthenticated, and doing so
        # avoids a browser re-challenge for every chunk. No lead data lives here.
        app.mount(
            "/assets", StaticFiles(directory=str(assets_dir)), name="dashboard-assets"
        )
    else:
        logger.warning(
            "DASHBOARD: no build output at %s — run `npm run build` in dashboard/web",
            DIST_DIR,
        )

    @app.get("/", include_in_schema=False)
    async def dashboard_root() -> RedirectResponse:
        return RedirectResponse(url="/infogatherer", status_code=307)

    @app.get("/favicon.ico", include_in_schema=False)
    async def dashboard_favicon():
        icon = DIST_DIR / "favicon.ico"
        if icon.is_file():
            return FileResponse(str(icon))
        raise HTTPException(status_code=404, detail="Not found")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def dashboard_spa(
        full_path: str,
        request: Request,
        _: str = Depends(require_dashboard_auth),
    ):
        path = "/" + full_path.lstrip("/")
        if _is_reserved(path):
            raise HTTPException(status_code=404, detail="Not found")

        if not INDEX_FILE.is_file():
            from fastapi.responses import HTMLResponse

            return HTMLResponse(_MISSING_BUILD_HTML, status_code=503)

        # no-store: index.html is the routing entry point and must never be
        # served stale after a redeploy, while /assets/* is content-hashed.
        return FileResponse(str(INDEX_FILE), headers={"Cache-Control": "no-store"})
