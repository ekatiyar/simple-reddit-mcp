import email.message
import io
import json
import socket
import urllib.error

import pytest

from simple_reddit_mcp import api


@pytest.fixture(autouse=True)
def reset_pacing(monkeypatch):
    monkeypatch.setattr(api, "_last_request", 0.0, raising=False)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(api.time, "sleep", slept.append)
    return slept


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status
        self.headers = email.message.Message()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(status: int, body: bytes, headers: dict | None = None):
    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(
        "https://arctic-shift.photon-reddit.com/api/posts/ids",
        status, "error", message, io.BytesIO(body),
    )


def install(monkeypatch, *responses):
    """Queue urlopen outcomes; each is a response or an exception to raise."""
    urls = []
    queue = list(responses)

    def fake_urlopen(req, timeout=None):
        urls.append(req.full_url if hasattr(req, "full_url") else req)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(api.request, "urlopen", fake_urlopen)
    return urls


def test_200_returns_the_data_payload(monkeypatch):
    install(monkeypatch, FakeResponse(json.dumps({"data": [{"id": "abc123x"}]}).encode()))
    assert api.get("/api/posts/ids", {"ids": "t3_abc123x"}) == [{"id": "abc123x"}]


def test_request_carries_a_descriptive_user_agent(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["ua"] = req.get_header("User-agent")
        return FakeResponse(b'{"data": []}')

    monkeypatch.setattr(api.request, "urlopen", fake_urlopen)
    api.get("/api/posts/ids", {"ids": "t3_abc123x"})
    assert "simple-reddit-mcp" in captured["ua"]


def test_query_omits_none_lowercases_bools_and_joins_lists(monkeypatch):
    urls = install(monkeypatch, FakeResponse(b'{"data": []}'))
    api.get("/api/posts/search", {
        "subreddit": "LoremIpsum",
        "author": None,
        "over_18": False,
        "spoiler": True,
        "fields": ["title", "author"],
        "limit": 25,
    })
    query = urls[0].split("?", 1)[1]
    assert "author=" not in query
    assert "over_18=false" in query
    assert "spoiler=true" in query
    assert "fields=title%2Cauthor" in query
    assert "limit=25" in query
    assert "subreddit=LoremIpsum" in query


def test_422_is_retried_once_then_returned_as_an_error(monkeypatch, error_422):
    body = json.dumps(error_422).encode()
    urls = install(monkeypatch, http_error(422, body), http_error(422, body))
    with pytest.raises(api.ApiError) as excinfo:
        api.get("/api/posts/search", {"title": "lorem"})
    assert "Timeout. Maybe slow down a bit" in str(excinfo.value)
    assert len(urls) == 2


def test_422_that_succeeds_on_retry_returns_data(monkeypatch, error_422):
    urls = install(
        monkeypatch,
        http_error(422, json.dumps(error_422).encode()),
        FakeResponse(json.dumps({"data": [{"id": "abc123x"}]}).encode()),
    )
    assert api.get("/api/posts/search", {"title": "lorem"}) == [{"id": "abc123x"}]
    assert len(urls) == 2


def test_5xx_is_retried_exactly_once_then_reported_clearly(monkeypatch):
    urls = install(monkeypatch, http_error(503, b"upstream down"), http_error(503, b"upstream down"))
    with pytest.raises(api.ApiError) as excinfo:
        api.get("/api/posts/ids", {"ids": "t3_abc123x"})
    assert len(urls) == 2
    message = str(excinfo.value)
    assert "503" in message
    assert "Traceback" not in message


def test_429_reports_seconds_until_reset(monkeypatch):
    install(monkeypatch, http_error(429, b'{"error": "rate limited"}',
                                    {"X-RateLimit-Reset": "22"}))
    with pytest.raises(api.ApiError) as excinfo:
        api.get("/api/posts/ids", {"ids": "t3_abc123x"})
    message = str(excinfo.value)
    assert "22" in message
    assert "second" in message.lower()


def test_429_is_not_retried(monkeypatch):
    urls = install(monkeypatch, http_error(429, b"{}", {"X-RateLimit-Reset": "5"}))
    with pytest.raises(api.ApiError):
        api.get("/api/posts/ids", {"ids": "t3_abc123x"})
    assert len(urls) == 1


def test_4xx_error_body_is_surfaced_verbatim(monkeypatch):
    body = json.dumps({"data": None, "error": "'title' query parameter requires one of: author, subreddit"}).encode()
    install(monkeypatch, http_error(400, body))
    with pytest.raises(api.ApiError) as excinfo:
        api.get("/api/posts/search", {"title": "lorem"})
    assert "requires one of: author, subreddit" in str(excinfo.value)


def test_non_json_body_does_not_leak_a_json_decode_error(monkeypatch):
    install(monkeypatch, FakeResponse(b"<html>maintenance</html>"))
    with pytest.raises(api.ApiError) as excinfo:
        api.get("/api/posts/ids", {"ids": "t3_abc123x"})
    assert "JSON" in str(excinfo.value)
    assert not isinstance(excinfo.value, json.JSONDecodeError)


def test_url_error_becomes_a_readable_connectivity_message(monkeypatch):
    install(monkeypatch, urllib.error.URLError("[Errno -3] Temporary failure in name resolution"))
    with pytest.raises(api.ApiError) as excinfo:
        api.get("/api/posts/ids", {"ids": "t3_abc123x"})
    assert "reach" in str(excinfo.value).lower()


def test_socket_timeout_becomes_a_readable_timeout_message(monkeypatch):
    install(monkeypatch, socket.timeout("timed out"))
    with pytest.raises(api.ApiError) as excinfo:
        api.get("/api/posts/ids", {"ids": "t3_abc123x"})
    assert "timed out" in str(excinfo.value).lower()


def test_requests_are_paced(monkeypatch, no_real_sleep):
    install(monkeypatch, FakeResponse(b'{"data": []}'), FakeResponse(b'{"data": []}'))
    api.get("/api/posts/ids", {"ids": "t3_abc123x"})
    assert no_real_sleep == []
    api.get("/api/posts/ids", {"ids": "t3_def456y"})
    assert len(no_real_sleep) == 1
    assert api.PACE_SECONDS - 0.05 < no_real_sleep[0] <= api.PACE_SECONDS
