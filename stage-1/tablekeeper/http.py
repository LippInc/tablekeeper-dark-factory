"""HTTP routes (§3, §6, §8): parse the request, call the domain, render JSON."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import auth, booking, domain, fixture, idempotency, schedule, snapshot
from .domain import User
from .errors import ApiError, malformed
from .fields import FieldReader
from .store import State, Store


class JsonResponse(JSONResponse):
    """`application/json; charset=utf-8`, with non-ASCII characters escaped, so any
    string a request carried (a lone surrogate included) renders as valid UTF-8."""

    media_type = "application/json; charset=utf-8"

    def render(self, content: Any) -> bytes:
        return json.dumps(content, allow_nan=False, separators=(",", ":")).encode("ascii")


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not JSON")


def parse_json_object(raw: bytes) -> dict:
    """A request body as a JSON object, whatever the Content-Type says (§5)."""
    try:
        body = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise malformed("the body is not valid JSON") from None
    if not isinstance(body, dict):
        raise malformed("the body must be a JSON object")
    return body


async def json_object(request: Request) -> dict:
    return parse_json_object(await request.body())


def _store(request: Request) -> Store:
    return request.app.state.store


def _caller(request: Request, state: State) -> User:
    return auth.authenticate(state, request.headers.get("authorization"))


async def _keyed_write(request: Request,
                       operation: Callable[[State, User, dict], dict]) -> Response:
    """A write under an `Idempotency-Key` (§7): the first use runs `operation` and answers
    201; a replay answers 200 with the original response and changes nothing.

    Precedence (D3): token, body, key, replay or reuse, then the operation's own checks.
    """
    raw = await request.body()
    async with _store(request).transaction() as state:
        user = _caller(request, state)
        body = parse_json_object(raw)
        scope = (user.id, request.method, request.url.path, idempotency.read_key(request.headers))
        original = idempotency.original_response(state, scope, body)
        if original is not None:
            return JsonResponse(original)
        response = operation(state, user, body)
        idempotency.record(state, scope, body, response)
        return JsonResponse(response, status_code=201)


# ---- test control and health ------------------------------------------------

async def health(request: Request) -> Response:
    return JsonResponse({"status": "ok"})


async def reset(request: Request) -> Response:
    state = await fixture.seed(fixture.parse(await json_object(request)))
    await _store(request).replace(state)
    return Response(status_code=204)


async def export_state(request: Request) -> Response:
    async with _store(request).transaction() as state:
        return JsonResponse(snapshot.export(state))


async def import_state(request: Request) -> Response:
    state = snapshot.restore(await json_object(request))
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


async def get_availability(request: Request) -> Response:
    reader = FieldReader()
    restaurant_id = reader.identifier_param(request.query_params, "restaurant_id")
    day = reader.date_param(request.query_params, "date")
    party_size = reader.integer_param(request.query_params, "party_size", minimum=1)
    reader.raise_first()
    async with _store(request).transaction() as state:
        restaurant = domain.find_restaurant(state, restaurant_id)
        return JsonResponse(schedule.availability(state, restaurant, day, party_size))


# ---- reservations -----------------------------------------------------------

async def create_reservation(request: Request) -> Response:
    return await _keyed_write(request, booking.create)


async def move_reservations(request: Request) -> Response:
    return await _keyed_write(request, booking.move)


async def list_reservations(request: Request) -> Response:
    async with _store(request).transaction() as state:
        user = _caller(request, state)
        return JsonResponse({"reservations": domain.reservations_of(state, user)})


async def get_reservation(request: Request) -> Response:
    async with _store(request).transaction() as state:
        user = _caller(request, state)
        reservation = domain.own_reservation(state, user, request.path_params["reference"])
        return JsonResponse(domain.show(state, reservation))


async def amend_reservation(request: Request) -> Response:
    raw = await request.body()
    async with _store(request).transaction() as state:
        user = _caller(request, state)
        body = parse_json_object(raw)
        return JsonResponse(booking.amend(state, user, request.path_params["reference"], body))


async def cancel_reservation(request: Request) -> Response:
    async with _store(request).transaction() as state:
        user = _caller(request, state)
        return JsonResponse(booking.cancel(state, user, request.path_params["reference"]))


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
    Route("/_test/export", export_state, methods=["GET"]),
    Route("/_test/import", import_state, methods=["POST"]),
    Route("/auth/signup", signup, methods=["POST"]),
    Route("/auth/login", login, methods=["POST"]),
    Route("/restaurants", list_restaurants, methods=["GET"]),
    Route("/restaurants/{restaurant_id}", get_restaurant, methods=["GET"]),
    Route("/availability", get_availability, methods=["GET"]),
    Route("/reservations", list_reservations, methods=["GET"]),
    Route("/reservations", create_reservation, methods=["POST"]),
    Route("/reservations/{reference}", get_reservation, methods=["GET"]),
    Route("/reservations/{reference}", amend_reservation, methods=["PATCH"]),
    Route("/reservations/{reference}/cancel", cancel_reservation, methods=["POST"]),
    Route("/reservation-moves", move_reservations, methods=["POST"]),
]


def create_app() -> Starlette:
    app = Starlette(routes=ROUTES, exception_handlers={
        ApiError: _api_error, HTTPException: _http_error, Exception: _unexpected})
    app.state.store = Store()
    return app
