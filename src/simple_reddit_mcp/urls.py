"""Turn anything a user can paste into Reddit thing ids (`t3_`/`t1_`)."""

from __future__ import annotations

import re

from . import api

BASE36 = r"[a-z0-9]{2,13}"

_COMMENTS_RE = re.compile(
    rf"/(?:r/[^/]+/)?comments/(?P<post>{BASE36})(?:/[^/]*(?:/(?P<comment>{BASE36}))?)?/?$",
    re.IGNORECASE,
)
_SHORT_RE = re.compile(r"^(?:/?(?:r|u|user)/[^/]+/s/[A-Za-z0-9]+)$")
_REDD_IT_RE = re.compile(rf"^/(?P<post>{BASE36})/?$", re.IGNORECASE)
_PREFIXED_RE = re.compile(rf"^(?P<kind>t[13])_(?P<id>{BASE36})$", re.IGNORECASE)
_BARE_RE = re.compile(rf"^{BASE36}$", re.IGNORECASE)

_REDDIT_HOSTS = {"reddit.com", "redd.it", "reddit-stream.com"}

_HELP = (
    "Pass a reddit thread URL (https://www.reddit.com/r/<sub>/comments/<id>/...), "
    "a share link (/r/<sub>/s/<code>), a redd.it link, or a bare/prefixed id "
    "such as abc123x or t3_abc123x."
)


def _reject(url_or_id: str) -> ValueError:
    return ValueError(f"Could not read a reddit post or comment id from url_or_id={url_or_id!r}. {_HELP}")


def normalize_id(value: str, kind: str) -> str:
    """Return `value` as a `t3_`/`t1_` prefixed id, rejecting the wrong kind."""
    text = (value or "").strip().lower()
    match = _PREFIXED_RE.match(text)
    if match:
        if match.group("kind") != kind:
            raise ValueError(f"Expected a {kind}_ id but got {value!r}.")
        return f"{kind}_{match.group('id')}"
    if _BARE_RE.match(text):
        return f"{kind}_{text}"
    raise ValueError(f"{value!r} is not a base-36 reddit id (e.g. abc123x or {kind}_abc123x).")


def normalize_ids(values: str, kind: str, limit: int = 500) -> str:
    """Normalize a comma separated id list into the form the API expects."""
    items = [item for item in re.split(r"[,\s]+", (values or "").strip()) if item]
    if not items:
        raise ValueError("No ids given.")
    if len(items) > limit:
        raise ValueError(f"Too many ids: {len(items)}. Arctic Shift accepts at most {limit} per request.")
    return ",".join(normalize_id(item, kind) for item in items)


def _split_path(url_or_id: str) -> str:
    """Return the path of a reddit URL, or the input unchanged if it isn't one."""
    text = url_or_id
    if "://" in text:
        scheme, _, rest = text.partition("://")
        host, _, path = rest.partition("/")
        host = host.split("@")[-1].split(":")[0].lower()
        registrable = ".".join(host.split(".")[-2:])
        if registrable not in _REDDIT_HOSTS:
            raise _reject(url_or_id)
        text = "/" + path
    return text.split("#", 1)[0].split("?", 1)[0]


def parse_target(url_or_id: str) -> tuple[str | None, str | None]:
    """Return `(post_id, comment_id)` as `t3_`/`t1_` ids; either may be None.

    Share links (`/r/<sub>/s/<code>`) are resolved through Arctic Shift's
    `/api/short_links` endpoint, which is the only branch that touches the
    network.
    """
    text = (url_or_id or "").strip()
    if not text:
        raise _reject(url_or_id)

    match = _PREFIXED_RE.match(text)
    if match:
        kind = match.group("kind").lower()
        thing = f"{kind}_{match.group('id').lower()}"
        return (thing, None) if kind == "t3" else (None, thing)
    if _BARE_RE.match(text):
        return f"t3_{text.lower()}", None

    path = _split_path(text)

    if _SHORT_RE.match(path):
        return parse_target(_resolve_short_link(path))

    match = _COMMENTS_RE.search(path)
    if match:
        comment = match.group("comment")
        return (
            f"t3_{match.group('post').lower()}",
            f"t1_{comment.lower()}" if comment else None,
        )

    match = _REDD_IT_RE.match(path)
    if match:
        return f"t3_{match.group('post').lower()}", None

    raise _reject(url_or_id)


def _resolve_short_link(path: str) -> str:
    """Expand a `/r/<sub>/s/<code>` share link into its real permalink."""
    if not path.startswith("/"):
        path = "/" + path
    entries = api.get("/api/short_links", {"paths": path}) or []
    for entry in entries:
        resolved = (entry or {}).get("resolved_path")
        if resolved:
            return resolved
    raise ValueError(
        f"Arctic Shift has not archived the share link {path!r}. "
        "Open it in a browser and pass the full /comments/ URL instead."
    )
