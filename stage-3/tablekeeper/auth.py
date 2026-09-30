"""Accounts, password hashing and bearer tokens (§6)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import secrets
from concurrent.futures import ThreadPoolExecutor

from .domain import User
from .errors import ApiError, unauthenticated
from .fields import FieldReader, at
from .store import State, Store, fresh

EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
MIN_PASSWORD_LENGTH = 8

# scrypt at n=2^14, r=8 costs about 16 MiB and a few tens of milliseconds per hash. The
# parameters travel inside every hash record, so they can be raised later without
# invalidating stored passwords.
SCRYPT_PARAMS = {"n": 2**14, "r": 8, "p": 1}
# The costliest parameters an imported hash record may carry: hashlib.scrypt's default
# memory limit, and a bound on the time one login may take.
MAX_SCRYPT_MEMORY = 32 * 1024 * 1024
MAX_SCRYPT_PARALLELISM = 4
_hashing = ThreadPoolExecutor(max_workers=4, thread_name_prefix="password-hash")


# ---- password hashing -------------------------------------------------------

def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # "surrogatepass": a JSON string may carry a lone surrogate, which plain UTF-8 refuses.
    return hashlib.scrypt(password.encode("utf-8", "surrogatepass"),
                          salt=salt, n=n, r=r, p=p, dklen=32)


def _hash_record(password: str) -> dict:
    salt = os.urandom(16)
    digest = _scrypt(password, salt, **SCRYPT_PARAMS)
    return {"algorithm": "scrypt", **SCRYPT_PARAMS,
            "salt": base64.b64encode(salt).decode("ascii"),
            "hash": base64.b64encode(digest).decode("ascii")}


def _matches(password: str, record: dict) -> bool:
    digest = _scrypt(password, base64.b64decode(record["salt"]),
                     n=record["n"], r=record["r"], p=record["p"])
    return hmac.compare_digest(digest, base64.b64decode(record["hash"]))


def is_hash_record(record: dict) -> bool:
    """Whether `record` is a scrypt hash record this service can verify against."""
    n, r, p = (record.get(name) for name in ("n", "r", "p"))
    if record.get("algorithm") != "scrypt" or not all(
            type(value) is int and value > 0 for value in (n, r, p)):
        return False
    if n < 2 or n & (n - 1) or 128 * r * n > MAX_SCRYPT_MEMORY or p > MAX_SCRYPT_PARALLELISM:
        return False
    try:
        return all(base64.b64decode(record[name], validate=True) for name in ("salt", "hash"))
    except (KeyError, TypeError, ValueError):
        return False


async def hash_password(password: str) -> dict:
    """A hash record for `password`, computed off the event loop."""
    return await asyncio.get_running_loop().run_in_executor(_hashing, _hash_record, password)


async def _password_matches(password: str, record: dict) -> bool:
    return await asyncio.get_running_loop().run_in_executor(_hashing, _matches, password, record)


# ---- requests ---------------------------------------------------------------

def read_identity(reader: FieldReader, obj: dict, path: str = "") -> tuple[str | None, str | None]:
    """An account's `email` and `display_name`, by the rules every account follows,
    whether it signs up or is seeded or imported (§4, §6)."""
    email = reader.read(obj, "email", "string", path)
    display_name = reader.read(obj, "display_name", "string", path)
    if email is not None and not EMAIL.fullmatch(email):
        reader.reject(at(path, "email"), "must have the form local@domain")
        email = None
    if display_name == "":
        reader.reject(at(path, "display_name"), "must not be empty")
        display_name = None
    return email, display_name


def _read_signup(body: dict) -> tuple[str, str, str]:
    reader = FieldReader()
    email, display_name = read_identity(reader, body)
    password = reader.read(body, "password", "string")
    if password is not None and len(password) < MIN_PASSWORD_LENGTH:
        reader.reject("password", f"must be at least {MIN_PASSWORD_LENGTH} characters")
    reader.raise_first()
    return email, password, display_name


def _read_login(body: dict) -> tuple[str, str]:
    reader = FieldReader()
    email = reader.read(body, "email", "string")
    password = reader.read(body, "password", "string")
    reader.raise_first()
    return email, password


def _start_session(state: State, user: User) -> dict:
    token = fresh(lambda: secrets.token_urlsafe(32), state.tokens)
    state.tokens[token] = user.id
    return {"user_id": user.id, "display_name": user.display_name, "token": token}


async def sign_up(store: Store, body: dict) -> dict:
    email, password, display_name = _read_signup(body)
    password_hash = await hash_password(password)
    async with store.transaction() as state:
        if state.user_by_email(email) is not None:
            raise ApiError(409, "email_taken", "that email is already registered")
        user = User(id=fresh(lambda: f"u_{secrets.token_hex(8)}", state.users),
                    email=email, display_name=display_name, password_hash=password_hash)
        state.add_user(user)
        return _start_session(state, user)


async def log_in(store: Store, body: dict) -> dict:
    email, password = _read_login(body)
    async with store.transaction() as state:
        user = state.user_by_email(email)
    if user is None or not await _password_matches(password, user.password_hash):
        raise unauthenticated("wrong email or password")
    async with store.transaction() as state:
        # A reset while the password was checked may have replaced the account.
        if state.users.get(user.id) is not user:
            raise unauthenticated("wrong email or password")
        return _start_session(state, user)


def optional_user(state: State, authorization: str | None) -> User | None:
    """The user a `Bearer <token>` header belongs to; None for a missing, malformed or
    unknown token."""
    scheme, _, token = (authorization or "").partition(" ")
    user_id = state.tokens.get(token.strip()) if scheme.lower() == "bearer" else None
    return None if user_id is None else state.users[user_id]


def authenticate(state: State, authorization: str | None) -> User:
    """The user a `Bearer <token>` header belongs to."""
    user = optional_user(state, authorization)
    if user is None:
        raise unauthenticated("a valid bearer token is required")
    return user
