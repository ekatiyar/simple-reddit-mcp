"""MCP server exposing the Arctic Shift Reddit archive over stdio."""

import functools
import sys
from typing import Annotated, Callable

from zeromcp import McpServer, McpToolError

from . import api, render, urls
from . import __version__

mcp = McpServer("reddit", __version__)

FRESHNESS = (
    "Caveat: Arctic Shift archives posts the moment they appear and backfills "
    "vote data after ~36h, so `score` and `num_comments` on anything newer than "
    "that are placeholders (usually 1 and 0) - never report them as real counts."
)

NARROWING_HINT = (
    " Try narrowing the query - add `subreddit`, `author`, or an `after`/`before` "
    "date range, or lower `limit`."
)


def _tool(func: Callable) -> Callable:
    """Turn expected failures into tool errors instead of tracebacks."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except api.ApiError as exc:
            message = str(exc)
            if any(word in message.lower() for word in ("timeout", "timed out", "slow down")):
                message += NARROWING_HINT
            raise McpToolError(message) from None
        except ValueError as exc:
            raise McpToolError(str(exc)) from None

    wrapper.__doc__ = f"{(func.__doc__ or '').strip()}\n\n{FRESHNESS}"
    return wrapper


def _limit(value: int, ceiling: int, name: str = "limit") -> int:
    if not 1 <= value <= ceiling:
        raise ValueError(f"`{name}` must be between 1 and {ceiling}, got {value}.")
    return value


@mcp.tool(read_only=True, idempotent=True, open_world=True)
@_tool
def get_thread(
    url_or_id: Annotated[str, "A reddit thread URL, share link, redd.it link, or post/comment id (bare or t3_/t1_ prefixed)."],
    comment_limit: Annotated[int, "Max comments to fetch, 0-25000. Use 0 for post metadata only."] = 100,
    parent_id: Annotated[str | None, "Comment id to focus on; only that subtree is returned."] = None,
    sort_top: Annotated[bool, "Order comments by score instead of reddit's tree order."] = False,
    max_chars: Annotated[int, "Character budget for the rendered output."] = render.DEFAULT_MAX_CHARS,
    raw: Annotated[bool, "Return the raw Arctic Shift JSON instead of markdown."] = False,
) -> str:
    """Read a reddit post and its comment tree from any reddit URL or id.

    The primary tool: give it whatever the user pasted. Comments come back as an
    indented markdown tree; collapsed branches show as `[+N more replies]`.
    """
    post_id, comment_id = urls.parse_target(url_or_id)
    if not 0 <= comment_limit <= 25000:
        raise ValueError(f"`comment_limit` must be between 0 and 25000, got {comment_limit}.")

    if post_id is None:
        found = api.get("/api/comments/ids", {"ids": comment_id, "fields": "link_id"})
        if not found:
            raise McpToolError(f"Comment {comment_id} not found in the Arctic Shift archive.")
        post_id = found[0].get("link_id")

    posts = api.get("/api/posts/ids", {"ids": post_id})
    if not posts:
        raise McpToolError(
            f"Post {post_id} not found in the Arctic Shift archive. Very new posts "
            "can take a few minutes to appear; deleted posts may never appear."
        )
    post = posts[0]

    focus = urls.normalize_id(parent_id, "t1") if parent_id else comment_id
    tree = []
    if comment_limit:
        tree = api.get("/api/comments/tree", {
            "link_id": post_id,
            "parent_id": focus,
            "limit": comment_limit,
        }) or []

    if raw:
        return render.render_raw({"post": post, "comments": tree}, max_chars=max_chars)
    return render.render_thread(post, tree, max_chars=max_chars, sort_top=sort_top)


@mcp.tool(read_only=True, idempotent=True, open_world=True)
@_tool
def get_posts(
    ids: Annotated[str, "Comma separated post ids, bare or t3_ prefixed. Up to 500."],
    fields: Annotated[str | None, "Comma separated field allowlist to shrink the response."] = None,
    max_chars: Annotated[int, "Character budget for the rendered output."] = render.DEFAULT_MAX_CHARS,
    raw: Annotated[bool, "Return the raw Arctic Shift JSON instead of markdown."] = False,
) -> str:
    """Look up posts in bulk by id.

    Use when you already have post ids (for example from `search_comments`
    results) and want their titles, authors and scores.
    """
    data = api.get("/api/posts/ids", {"ids": urls.normalize_ids(ids, "t3"), "fields": fields}) or []
    if raw:
        return render.render_raw(data, max_chars=max_chars)
    return render.render_posts(data, max_chars=max_chars)


@mcp.tool(read_only=True, idempotent=True, open_world=True)
@_tool
def get_comments(
    ids: Annotated[str, "Comma separated comment ids, bare or t1_ prefixed. Up to 500."],
    fields: Annotated[str | None, "Comma separated field allowlist to shrink the response."] = None,
    max_chars: Annotated[int, "Character budget for the rendered output."] = render.DEFAULT_MAX_CHARS,
    raw: Annotated[bool, "Return the raw Arctic Shift JSON instead of markdown."] = False,
) -> str:
    """Look up comments in bulk by id.

    Use for the comment ids returned inside a `[+N more replies]` marker, or any
    comment permalink you already resolved.
    """
    data = api.get("/api/comments/ids", {"ids": urls.normalize_ids(ids, "t1"), "fields": fields}) or []
    if raw:
        return render.render_raw(data, max_chars=max_chars)
    return render.render_comments(data, max_chars=max_chars)


@mcp.tool(read_only=True, idempotent=True, open_world=True)
@_tool
def search_posts(
    subreddit: Annotated[str | None, "Restrict to one subreddit."] = None,
    author: Annotated[str | None, "Restrict to one author."] = None,
    query: Annotated[str | None, "Keyword search over title and selftext. Needs `subreddit` or `author`."] = None,
    title: Annotated[str | None, "Keyword search over the title only. Needs `subreddit` or `author`."] = None,
    selftext: Annotated[str | None, "Keyword search over the body only. Needs `subreddit` or `author`."] = None,
    url: Annotated[str | None, "Prefix match on the post's outbound URL."] = None,
    after: Annotated[str | None, "Earliest creation date: epoch, ISO date, or relative like `3d` / `1year`."] = None,
    before: Annotated[str | None, "Latest creation date, same formats as `after`."] = None,
    limit: Annotated[int, "Number of posts to return, 1-100."] = 25,
    sort: Annotated[str | None, "`asc` or `desc` by creation time."] = None,
    fields: Annotated[str | None, "Comma separated field allowlist to shrink the response."] = None,
    max_chars: Annotated[int, "Character budget for the rendered output."] = render.DEFAULT_MAX_CHARS,
    raw: Annotated[bool, "Return the raw Arctic Shift JSON instead of markdown."] = False,
) -> str:
    """Find posts by subreddit, author, keyword or date range.

    Keyword parameters (`query`, `title`, `selftext`) are only accepted together
    with `subreddit` or `author`, and can still time out on very busy ones - a
    date range makes them reliable.
    """
    data = api.get("/api/posts/search", {
        "subreddit": subreddit, "author": author, "query": query, "title": title,
        "selftext": selftext, "url": url, "after": after, "before": before,
        "limit": _limit(limit, 100), "sort": sort, "fields": fields,
    }) or []
    if raw:
        return render.render_raw(data, max_chars=max_chars)
    return render.render_posts(data, max_chars=max_chars)


@mcp.tool(read_only=True, idempotent=True, open_world=True)
@_tool
def search_comments(
    subreddit: Annotated[str | None, "Restrict to one subreddit."] = None,
    author: Annotated[str | None, "Restrict to one author. On its own this is a user's comment history."] = None,
    body: Annotated[str | None, "Keyword search over the comment body. Needs `subreddit`, `author`, `link_id` or `parent_id`."] = None,
    link_id: Annotated[str | None, "Only comments under this post id."] = None,
    parent_id: Annotated[str | None, "Only replies to this comment id."] = None,
    after: Annotated[str | None, "Earliest creation date: epoch, ISO date, or relative like `3d` / `1year`."] = None,
    before: Annotated[str | None, "Latest creation date, same formats as `after`."] = None,
    limit: Annotated[int, "Number of comments to return, 1-100."] = 25,
    sort: Annotated[str | None, "`asc` or `desc` by creation time."] = None,
    fields: Annotated[str | None, "Comma separated field allowlist to shrink the response."] = None,
    max_chars: Annotated[int, "Character budget for the rendered output."] = render.DEFAULT_MAX_CHARS,
    raw: Annotated[bool, "Return the raw Arctic Shift JSON instead of markdown."] = False,
) -> str:
    """Find comments by subreddit, author, keyword, post or date range.

    With `author` alone this doubles as user comment history. Comment keyword
    search is the slowest endpoint - pair `body` with a subreddit, an author or a
    date range.
    """
    data = api.get("/api/comments/search", {
        "subreddit": subreddit, "author": author, "body": body,
        "link_id": urls.normalize_id(link_id, "t3") if link_id else None,
        "parent_id": urls.normalize_id(parent_id, "t1") if parent_id else None,
        "after": after, "before": before, "limit": _limit(limit, 100),
        "sort": sort, "fields": fields,
    }) or []
    if raw:
        return render.render_raw(data, max_chars=max_chars)
    return render.render_comments(data, max_chars=max_chars)


@mcp.tool(read_only=True, idempotent=True, open_world=True)
@_tool
def search_subreddits(
    subreddit: Annotated[str | None, "Exact subreddit name."] = None,
    subreddit_prefix: Annotated[str | None, "Match subreddits whose name starts with this."] = None,
    min_subscribers: Annotated[int | None, "Only subreddits with at least this many subscribers."] = None,
    max_subscribers: Annotated[int | None, "Only subreddits with at most this many subscribers."] = None,
    over18: Annotated[bool | None, "Filter on the NSFW flag."] = None,
    after: Annotated[str | None, "Earliest subreddit creation date: epoch, ISO date, or relative like `1year`."] = None,
    before: Annotated[str | None, "Latest subreddit creation date, same formats as `after`."] = None,
    limit: Annotated[int, "Number of subreddits to return, 1-1000."] = 25,
    sort: Annotated[str | None, "`asc` or `desc`."] = None,
    sort_type: Annotated[str | None, "`subscribers` (default), `created_utc`, or `subreddit`."] = None,
    fields: Annotated[str | None, "Comma separated field allowlist to shrink the response."] = None,
    max_chars: Annotated[int, "Character budget for the rendered output."] = render.DEFAULT_MAX_CHARS,
    raw: Annotated[bool, "Return the raw Arctic Shift JSON instead of markdown."] = False,
) -> str:
    """Find subreddits by name, prefix, subscriber count or age.

    Subreddit records are refreshed infrequently, so subscriber counts lag
    reality by more than the ~36h that applies to posts and comments.
    """
    data = api.get("/api/subreddits/search", {
        "subreddit": subreddit, "subreddit_prefix": subreddit_prefix,
        "min_subscribers": min_subscribers, "max_subscribers": max_subscribers,
        "over18": over18, "after": after, "before": before,
        "limit": _limit(limit, 1000), "sort": sort, "sort_type": sort_type,
        "fields": fields,
    }) or []
    if raw:
        return render.render_raw(data, max_chars=max_chars)
    return render.render_subreddits(data, max_chars=max_chars)


def main() -> None:
    print(f"simple-reddit-mcp {__version__}: serving reddit tools over stdio",
          file=sys.stderr, flush=True)
    mcp.stdio()


if __name__ == "__main__":
    main()
