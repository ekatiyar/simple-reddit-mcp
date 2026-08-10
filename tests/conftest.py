"""Shared fixtures. The whole suite is offline: nothing here opens a socket.

The JSON fixtures mirror response *shapes* recorded from Arctic Shift; every
value in them is invented. Shape facts each one preserves:

  post.json       /api/posts/ids -> {"data": [ {...} ]}. One post object with the
                  real ~114-field spread, including title, author, score,
                  num_comments, created_utc, selftext, permalink, url.

  comment_tree.json
                  /api/comments/tree -> {"data": [ {"kind": "t1", "data": {...}} ]}.
                  `replies` is either "" (leaf) or
                  {"kind": "Listing", "data": {"dist": N, "children": [...]}}.
                  Deliberately includes: three levels of nesting; `"depth": null`
                  on every comment (the wire omits or nulls it, so indentation
                  must come from recursion); one
                  {"kind": "more", "data": {"count": 6, "children": [...]}} node;
                  one "[deleted]" body with "author": null; and one very long
                  body to drive truncation.

  search_posts.json      /api/posts/search -> {"data": [ post, ... ]}.
  search_subreddits.json /api/subreddits/search -> {"data": [ subreddit, ... ]}.
  error_422.json         the error body shape: {"data": null, "error": "..."}.
                         Arctic Shift sends these with a 4xx status, not a 200.
"""

import json
import pathlib

import pytest

from simple_reddit_mcp import api

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def post():
    return load("post")["data"][0]


@pytest.fixture
def comment_tree():
    return load("comment_tree")["data"]


@pytest.fixture
def search_posts():
    return load("search_posts")["data"]


@pytest.fixture
def search_subreddits():
    return load("search_subreddits")["data"]


@pytest.fixture
def error_422():
    return load("error_422")


@pytest.fixture
def stub_api(monkeypatch):
    """Install a fake api.get. Returns the list that records (path, params).

    `handler` is called as handler(path, params) and may return a value or
    raise, so a test can drive either success or any failure mode.
    """

    def install(handler):
        calls = []

        def fake_get(path, params=None):
            calls.append((path, dict(params or {})))
            return handler(path, dict(params or {}))

        monkeypatch.setattr(api, "get", fake_get)
        return calls

    return install
