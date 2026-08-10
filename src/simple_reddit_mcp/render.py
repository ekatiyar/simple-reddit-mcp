"""Compact markdown renderers.

A single Arctic Shift post object carries ~114 fields and a busy comment tree is
hundreds of KB of JSON; these renderers project the ~8 fields that matter and
keep the result inside a character budget.
"""

from __future__ import annotations

import json
import time
from typing import Any

DEFAULT_MAX_CHARS = 40000
BODY_MAX_CHARS = 1500
INDENT = "  "

# Posts younger than this have placeholder score/num_comments (not yet backfilled).
BACKFILL_SECONDS = 36 * 3600

FRESHNESS_NOTE = (
    "_Posted under 36h ago: Arctic Shift has not backfilled `score` / "
    "`num_comments` yet, so those numbers are placeholders, not real vote counts._"
)


def now() -> float:
    return time.time()


def _age(created_utc: Any) -> str:
    try:
        seconds = now() - float(created_utc)
    except (TypeError, ValueError):
        return "unknown age"
    if seconds < 0:
        return "just now"
    for size, unit in ((31557600, "y"), (2629800, "mo"), (604800, "w"),
                       (86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{int(seconds // size)}{unit} ago"
    return f"{int(seconds)}s ago"


def _author(thing: dict) -> str:
    author = thing.get("author")
    if not author or author in ("[deleted]", "[removed]"):
        return "u/[deleted]"
    return f"u/{author}"


def _clip(text: str, limit: int = BODY_MAX_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " ... [body truncated]"


def _permalink(thing: dict) -> str:
    permalink = thing.get("permalink") or ""
    return f"https://www.reddit.com{permalink}" if permalink else ""


def _is_fresh(thing: dict) -> bool:
    try:
        return now() - float(thing.get("created_utc")) < BACKFILL_SECONDS
    except (TypeError, ValueError):
        return False


def _post_header(post: dict) -> list[str]:
    subreddit = post.get("subreddit") or "?"
    lines = [f"# {post.get('title') or '(no title)'}", ""]
    meta = [
        f"r/{subreddit}",
        _author(post),
        f"{post.get('score', 0)} points",
        f"{post.get('num_comments', 0)} comments",
        _age(post.get("created_utc")),
    ]
    lines.append(" | ".join(meta))
    permalink = _permalink(post)
    if permalink:
        lines.append(permalink)
    link = post.get("url") or ""
    if link and not link.startswith("https://www.reddit.com"):
        lines.append(f"Link: {link}")
    if _is_fresh(post):
        lines += ["", FRESHNESS_NOTE]
    selftext = _clip(post.get("selftext") or "")
    if selftext:
        lines += ["", selftext]
    return lines


def _comment_lines(node: dict, depth: int, out: list[str]) -> None:
    pad = INDENT * depth
    kind = node.get("kind")
    if kind == "more":
        count = (node.get("data") or {}).get("count") or len(
            (node.get("data") or {}).get("children") or []
        )
        out.append(f"{pad}- _[+{count} more replies]_")
        return
    if kind != "t1":
        return

    data = node.get("data") or {}
    body = _clip(data.get("body") or "").replace("\n", f"\n{pad}{INDENT}")
    header = f"{_author(data)} ({data.get('score', 0)} pts, {_age(data.get('created_utc'))})"
    out.append(f"{pad}- **{header}**: {body}")

    replies = data.get("replies")
    if isinstance(replies, dict):
        for child in _ordered(replies.get("data", {}).get("children") or []):
            _comment_lines(child, depth + 1, out)


def _ordered(nodes: list, sort_top: bool = False) -> list:
    if not sort_top:
        return nodes
    def key(node):
        if node.get("kind") == "more":
            return (1, 0)
        return (0, -(node.get("data") or {}).get("score", 0))
    return sorted(nodes, key=key)


def _budget(lines: list[str], max_chars: int, narrow: str) -> str:
    notice = (
        f"\n\n_[output truncated at {max_chars} characters - "
        f"narrow with `{narrow}` or raise `max_chars`]_"
    )
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(notice))
    return text[:keep].rstrip() + notice


def render_thread(
    post: dict | None,
    tree: list,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    sort_top: bool = False,
) -> str:
    lines: list[str] = []
    if post:
        lines += _post_header(post)
        lines += ["", "---", ""]
    if not tree:
        lines.append("_No comments._" if post else "No comments found.")
    for node in _ordered(tree, sort_top):
        _comment_lines(node, 0, lines)
    return _budget(lines, max_chars, "comment_limit")


def render_posts(posts: list, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    if not posts:
        return "No posts matched."
    lines = [f"{len(posts)} post(s):", ""]
    fresh = False
    for post in posts:
        fresh = fresh or _is_fresh(post)
        lines.append(
            f"- **{post.get('title') or '(no title)'}** "
            f"(`{post.get('id', '?')}`) - r/{post.get('subreddit', '?')} | "
            f"{_author(post)} | {post.get('score', 0)} points | "
            f"{post.get('num_comments', 0)} comments | {_age(post.get('created_utc'))}"
        )
        permalink = _permalink(post)
        if permalink:
            lines.append(f"{INDENT}{permalink}")
        selftext = _clip(post.get("selftext") or "", 300)
        if selftext:
            lines.append(f"{INDENT}{selftext.splitlines()[0]}")
    if fresh:
        lines += ["", FRESHNESS_NOTE]
    return _budget(lines, max_chars, "limit")


def render_comments(comments: list, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    if not comments:
        return "No comments matched."
    lines = [f"{len(comments)} comment(s):", ""]
    for comment in comments:
        lines.append(
            f"- **{_author(comment)}** in r/{comment.get('subreddit', '?')} "
            f"({comment.get('score', 0)} pts, {_age(comment.get('created_utc'))}, "
            f"`{comment.get('id', '?')}` under `{comment.get('link_id', '?')}`)"
        )
        body = _clip(comment.get("body") or "")
        lines.append(f"{INDENT}{body}".replace("\n", f"\n{INDENT}"))
    return _budget(lines, max_chars, "limit")


def render_subreddits(subreddits: list, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    if not subreddits:
        return "No subreddits matched."
    lines = [f"{len(subreddits)} subreddit(s):", ""]
    for subreddit in subreddits:
        name = subreddit.get("display_name") or "?"
        subscribers = subreddit.get("subscribers") or 0
        nsfw = " [NSFW]" if subreddit.get("over18") else ""
        lines.append(
            f"- **r/{name}**{nsfw} - {subscribers:,} subscribers | "
            f"created {_age(subreddit.get('created_utc'))}"
        )
        description = _clip(subreddit.get("public_description") or "", 200)
        if description:
            lines.append(f"{INDENT}{description.splitlines()[0]}")
    return _budget(lines, max_chars, "limit")


def render_raw(payload: Any, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    notice = f"\n... [raw output truncated at {max_chars} characters; this JSON is incomplete]"
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - len(notice))] + notice
