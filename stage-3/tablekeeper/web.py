"""The browser screens (stage 2): one HTML shell for every screen route, and the static
assets it loads (scripts, styles, fonts), all served by this service under `/assets`.

The shell's script renders the screen for the path it was loaded on; the screens talk to
the same JSON API as any other client.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

STATIC = Path(__file__).parent / "static"
SCREENS = ("/", "/signup", "/login", "/lookup")

mimetypes.add_type("font/woff2", ".woff2")  # not every base image's MIME table knows it


async def shell(request: Request) -> Response:
    return FileResponse(STATIC / "index.html", media_type="text/html; charset=utf-8")


ROUTES = [Route(path, shell, methods=["GET"]) for path in SCREENS] + [
    Mount("/assets", app=StaticFiles(directory=STATIC), name="assets")]
