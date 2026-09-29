"""HTTP routes (§3, §6, §8): parse the request, call the domain, render JSON."""
from __future__ import annotations

import json
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import auth, domain, fixture
from .errors import ApiError, malformed
from .store import Store


class JsonResponse(JSONResponse):
    """`application/json; charset=utf-8`, with non-ASCII characters escaped, so any
    string a request carried (a lone surrogate included) renders as valid UTF-8."""

    media_type = "application/json; charset=utf-8"

    def render(self, content: Any) -> bytes:
        return json.dumps(content, allow_nan=False, separators=(",", ":")).encode("ascii")


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not JSON")


async def json_object(request: Request) -> dict:
    """The request body as a JSON object, whatever the Content-Type says (§5)."""
    try:
        body = json.loads(await request.body(), parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise malformed("the body is not valid JSON") from None
    if not isinstance(body, dict):
        raise malformed("the body must be a JSON object")
    return body


def _store(request: Request) -> Store:
    return request.app.state.store


# ---- test control and health ------------------------------------------------

async def health(request: Request) -> Response:
    return JsonResponse({"status": "ok"})


async def reset(request: Request) -> Response:
    state = await fixture.seed(fixture.parse(await json_object(request)))
    await _store(request).replace(state)
    return Response(status_code=204)


# ---- accounts ---------------------------------------------------------------

async def signup(request: Request) -> Response:
    return JsonResponse(await auth.sign_up(_store(request), await json_object(request)),
                        status_code=201)


async def login(request: Request) -> Response:
    return JsonResponse(await auth.log_in(_store(request), await json_object(request)))


# ---- restaurants (public) ---------------------------------------------------

async def list_restaurants(request: Request) -> Response:
    async with _store(request).transaction() as state:
        return JsonResponse({"restaurants": [domain.restaurant_summary(r)
                                             for r in state.restaurants.values()]})


async def get_restaurant(request: Request) -> Response:
    async with _store(request).transaction() as state:
        restaurant = domain.find_restaurant(state, request.path_params["restaurant_id"])
        return JsonResponse(domain.restaurant_detail(restaurant))


# ---- reservations -----------------------------------------------------------

async def list_reservations(request: Request) -> Response:
    async with _store(request).transaction() as state:
        user = auth.authenticate(state, request.headers.get("authorization"))
        return JsonResponse({"reservations": domain.reservations_of(state, user)})


async def get_reservation(request: Request) -> Response:
    async with _store(request).transaction() as state:
        user = auth.authenticate(state, request.headers.get("authorization"))
        reservation = domain.own_reservation(state, user, request.path_params["reference"])
        return JsonResponse(domain.show(state, reservation))


# ---- errors -----------------------------------------------------------------

_HTTP_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}


async def _api_error(request: Request, exc: ApiError) -> Response:
    return JsonResponse(exc.body(), status_code=exc.status)


async def _http_error(request: Request, exc: HTTPException) -> Response:
    """The router's own refusals (unknown path, unsupported method) in the §5 shape."""
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    return JsonResponse({"error": {"code": code, "message": exc.detail}},
                        status_code=exc.status_code, headers=exc.headers)


async def _unexpected(request: Request, exc: Exception) -> Response:
    return JsonResponse({"error": {"code": "internal_error", "message": "unexpected error"}},
                        status_code=500)


ROUTES = [
    Route("/health", health, methods=["GET"]),
    Route("/_test/reset", reset, methods=["POST"]),
    Route("/auth/signup", signup, methods=["POST"]),
    Route("/auth/login", login, methods=["POST"]),
    Route("/restaurants", list_restaurants, methods=["GET"]),
    Route("/restaurants/{restaurant_id}", get_restaurant, methods=["GET"]),
    Route("/reservations", list_reservations, methods=["GET"]),
    Route("/reservations/{reference}", get_reservation, methods=["GET"]),
]


def create_app() -> Starlette:
    app = Starlette(routes=ROUTES, exception_handlers={
        ApiError: _api_error, HTTPException: _http_error, Exception: _unexpected})
    app.state.store = Store()
    return app
