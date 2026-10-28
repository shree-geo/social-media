"""Minimal Meta Graph API client shared by Messenger and (Phase 4) WhatsApp.

* Every call with a user/page token carries ``appsecret_proof`` (HMAC of the token with
  the app secret), so a leaked token cannot be used from outside our servers.
* Errors become :class:`GraphError`, classified as token-invalid / transient / permanent.
* Tokens never appear in logs or exception messages.
"""

import hashlib
import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

TIMEOUT = httpx.Timeout(15.0, connect=5.0)
# Tests replace this to serve recorded Graph responses (httpx.MockTransport).
transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None

_RATE_LIMIT_CODES = frozenset({4, 17, 32, 613, 80001, 80006})
_TRANSIENT_CODES = frozenset({1, 2})  # "unknown error" / "service temporarily unavailable"
_TOKEN_CODES = frozenset({102, 190})


@dataclass
class GraphError(Exception):
    message: str
    code: int | None = None
    subcode: int | None = None
    http_status: int | None = None
    fbtrace_id: str | None = None

    def __str__(self) -> str:
        return f"Meta error {self.code or self.http_status}: {self.message}"

    @property
    def token_invalid(self) -> bool:
        """Expired, revoked, password changed, app removed: the user must reconnect."""
        return self.code in _TOKEN_CODES

    @property
    def transient(self) -> bool:
        """Worth retrying: network failure, Meta outage (5xx) or rate limit."""
        if self.http_status is None or self.http_status >= 500:
            return True
        return self.code in _RATE_LIMIT_CODES or self.code in _TRANSIENT_CODES

    @property
    def short_code(self) -> str:
        return f"meta_{self.code}" + (f"_{self.subcode}" if self.subcode else "") if self.code else "meta_error"


def appsecret_proof(token: str) -> str:
    return hmac.new(get_settings().meta_app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def app_access_token() -> str:
    settings = get_settings()
    return f"{settings.meta_app_id}|{settings.meta_app_secret}"


def _base_url() -> str:
    version = get_settings().meta_graph_api_version
    if not version:
        raise GraphError("META_GRAPH_API_VERSION is not configured")
    return f"https://graph.facebook.com/{version}"


def _client() -> httpx.AsyncClient:
    transport = transport_factory() if transport_factory else None
    return httpx.AsyncClient(base_url=_base_url(), timeout=TIMEOUT, transport=transport)


def _parse_error(response: httpx.Response) -> GraphError:
    try:
        error = response.json().get("error", {})
    except ValueError:
        error = {}
    return GraphError(
        message=str(error.get("message") or response.reason_phrase or "Unknown error")[:300],
        code=error.get("code"),
        subcode=error.get("error_subcode"),
        http_status=response.status_code,
        fbtrace_id=error.get("fbtrace_id"),
    )


async def request(
    method: str,
    path: str,
    *,
    token: str,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    proof: bool = True,
) -> dict[str, Any]:
    query: dict[str, Any] = {**(params or {}), "access_token": token}
    if proof:
        query["appsecret_proof"] = appsecret_proof(token)
    try:
        async with _client() as client:
            response = await client.request(method, path, params=query, json=json)
    except httpx.HTTPError as exc:
        # Never include the URL: it carries the token in the query string.
        raise GraphError(f"Network error talking to Meta ({type(exc).__name__})") from None
    if response.status_code >= 400:
        error = _parse_error(response)
        log.warning(
            "graph_error",
            method=method,
            path=path.split("?")[0],
            status=response.status_code,
            meta_code=error.code,
            meta_subcode=error.subcode,
            fbtrace_id=error.fbtrace_id,
        )
        raise error
    data: dict[str, Any] = response.json()
    return data


async def get(path: str, *, token: str, **params: Any) -> dict[str, Any]:
    return await request("GET", path, token=token, params=params)


async def post(path: str, *, token: str, json: Mapping[str, Any] | None = None, **params: Any) -> dict[str, Any]:
    return await request("POST", path, token=token, params=params, json=json)


async def delete(path: str, *, token: str, **params: Any) -> dict[str, Any]:
    return await request("DELETE", path, token=token, params=params)


async def debug_token(input_token: str) -> dict[str, Any]:
    """Who issued this token, to which app, which user, with which scopes, until when."""
    data = await request(
        "GET", "/debug_token", token=app_access_token(), params={"input_token": input_token}, proof=False
    )
    return dict(data.get("data") or {})


async def exchange_for_long_lived(user_token: str) -> str:
    """Short-lived user token (from the login dialog) → long-lived (~60 days) user token.

    Page tokens derived from a long-lived user token do not expire on their own.
    """
    settings = get_settings()
    data = await request(
        "GET",
        "/oauth/access_token",
        token=app_access_token(),
        params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "fb_exchange_token": user_token,
        },
        proof=False,
    )
    token = data.get("access_token")
    if not isinstance(token, str):
        raise GraphError("Meta did not return a long-lived token")
    return token


async def exchange_code(code: str) -> str:
    """Embedded Signup code (single use, short-lived) → business integration system user token."""
    settings = get_settings()
    data = await request(
        "GET",
        "/oauth/access_token",
        token=app_access_token(),
        params={"client_id": settings.meta_app_id, "client_secret": settings.meta_app_secret, "code": code},
        proof=False,
    )
    token = data.get("access_token")
    if not isinstance(token, str):
        raise GraphError("Meta did not return an access token")
    return token
