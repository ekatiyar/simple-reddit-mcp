"""Minimal keyless HTTP client for the Arctic Shift API.

Arctic Shift is a free service with no uptime guarantee, so every failure mode
here is converted into an `ApiError` carrying a sentence a model can act on.
Nothing raises a bare urllib or JSON exception past this module.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, parse, request

BASE_URL = "https://arctic-shift.photon-reddit.com"
USER_AGENT = "simple-reddit-mcp/0.1.0 (+https://github.com/ekatiyar/simple-reddit-mcp)"
TIMEOUT_SECONDS = 60

# ~0.4s between requests keeps normal use under Arctic Shift's burst rate limit.
PACE_SECONDS = 0.4

# A 422 is usually a cold query planner, not a bad query - worth one retry (5xx too).
RETRY_STATUSES = frozenset({422, 500, 502, 503, 504})

_last_request = 0.0


class ApiError(Exception):
    """A request failed in a way the caller should report, not crash on."""


def _query(params: dict[str, Any] | None) -> str:
    pairs = []
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            value = ",".join(str(item) for item in value)
        pairs.append((key, str(value)))
    return parse.urlencode(pairs)


def _pace() -> None:
    global _last_request
    wait = PACE_SECONDS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _decode(body: bytes) -> Any:
    try:
        return json.loads(body)
    except ValueError:
        raise ApiError(
            "Arctic Shift returned a non-JSON response "
            f"({len(body)} bytes). The service may be down or behind an error page."
        ) from None


def _error_message(status: int, body: bytes) -> str:
    try:
        detail = json.loads(body).get("error")
    except ValueError:
        detail = None
    if not detail:
        detail = body.decode("utf-8", "replace").strip()[:200] or "no detail"
    return f"Arctic Shift error (HTTP {status}): {detail}"


def _attempt(url: str) -> Any:
    _pace()
    req = request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            payload = _decode(response.read())
    except error.HTTPError as exc:
        body = b""
        try:
            body = exc.read()
        except Exception:  # noqa: BLE001 - a body-less error is still an error
            pass
        if exc.code == 429:
            reset = (exc.headers or {}).get("X-RateLimit-Reset") if exc.headers else None
            wait = f"{reset} seconds" if reset else "a while"
            raise ApiError(
                f"Rate limited by Arctic Shift (HTTP 429). Wait {wait} before retrying."
            ) from None
        raise _Retryable(exc.code, _error_message(exc.code, body)) from None
    except TimeoutError:
        raise ApiError(
            f"Request to Arctic Shift timed out after {TIMEOUT_SECONDS}s."
        ) from None
    except error.URLError as exc:
        raise ApiError(
            f"Cannot reach Arctic Shift ({BASE_URL}): {exc.reason}. "
            "Check network connectivity, or the status page at "
            "https://status.arctic-shift.photon-reddit.com"
        ) from None
    except OSError as exc:
        raise ApiError(f"Cannot reach Arctic Shift ({BASE_URL}): {exc}") from None

    if isinstance(payload, dict) and payload.get("error"):
        raise ApiError(f"Arctic Shift error: {payload['error']}")
    if not isinstance(payload, dict) or "data" not in payload:
        raise ApiError("Arctic Shift returned an unexpected JSON shape (no 'data' key).")
    return payload["data"]


class _Retryable(ApiError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET an Arctic Shift endpoint and return its `data` payload.

    Retries once on 422/5xx. Raises `ApiError` on any failure.
    """
    url = f"{BASE_URL}{path}"
    query = _query(params)
    if query:
        url = f"{url}?{query}"

    for attempt in (1, 2):
        try:
            return _attempt(url)
        except _Retryable as exc:
            if attempt == 2 or exc.status not in RETRY_STATUSES:
                raise ApiError(str(exc)) from None
