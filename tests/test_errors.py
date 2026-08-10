"""Every failure mode must reach the model as readable text.

This is the offline substitute for live testing: rather than asserting that
Arctic Shift is up, it asserts that when Arctic Shift misbehaves the tool call
still returns an `isError` result with a usable message - and that the server
survives to answer the next call. Failures are injected at the transport
(`urlopen`) so the real `api.get` path runs, and the tool result is read back
through `tools/call` exactly as a client would see it.
"""

import email.message
import io
import json
import socket
import urllib.error

import pytest

from simple_reddit_mcp import api, server

from test_api import FakeResponse, http_error


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(api, "_last_request", 0.0, raising=False)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: None)

    def blocked(*args, **kwargs):
        raise AssertionError("test tried to open a socket")

    monkeypatch.setattr(api.request, "urlopen", blocked)


def call(name, arguments):
    return server.mcp.registry.dispatch({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })


def result_of(response):
    assert "error" not in response, response
    return response["result"]


def text_of(response):
    result = result_of(response)
    assert result["content"][0]["type"] == "text"
    return result["content"][0]["text"]


def transport(monkeypatch, *outcomes):
    """Queue urlopen outcomes; the last one repeats so retries stay covered.

    Outcomes may be callables, because a retry must see a *fresh* exception -
    an HTTPError's body is a stream that only reads once, exactly as urllib
    behaves against the real service.
    """
    queue = list(outcomes)

    def fake_urlopen(req, timeout=None):
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(outcome) and not isinstance(outcome, Exception):
            outcome = outcome()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(api.request, "urlopen", fake_urlopen)


THREAD_ARGS = {"url_or_id": "https://www.reddit.com/r/LoremIpsum/comments/abc123x/dolor/"}


def test_422_timeout_surfaces_and_suggests_narrowing(monkeypatch, error_422):
    body = json.dumps(error_422).encode()
    transport(monkeypatch, lambda: http_error(422, body))
    response = call("search_posts", {"subreddit": "LoremIpsum", "title": "lorem"})
    assert result_of(response)["isError"] is True
    message = text_of(response)
    assert "Timeout. Maybe slow down a bit" in message
    assert "narrow" in message.lower()


def test_429_names_the_wait_in_seconds(monkeypatch):
    transport(monkeypatch, http_error(429, b"{}", {"X-RateLimit-Reset": "22"}))
    response = call("get_thread", THREAD_ARGS)
    assert result_of(response)["isError"] is True
    message = text_of(response)
    assert "22" in message and "second" in message.lower()


def test_503_is_plain_text_with_no_traceback(monkeypatch):
    transport(monkeypatch, lambda: http_error(503, b"Service Unavailable"))
    response = call("get_thread", THREAD_ARGS)
    assert result_of(response)["isError"] is True
    message = text_of(response)
    assert "503" in message
    assert "Traceback" not in message
    assert "simple_reddit_mcp" not in message


def test_dns_failure_is_a_readable_connectivity_message(monkeypatch):
    transport(monkeypatch, urllib.error.URLError("[Errno -3] Temporary failure in name resolution"))
    response = call("get_thread", THREAD_ARGS)
    assert result_of(response)["isError"] is True
    assert "reach" in text_of(response).lower()
    assert "Traceback" not in text_of(response)


def test_socket_timeout_is_a_readable_timeout_message(monkeypatch):
    transport(monkeypatch, socket.timeout("timed out"))
    response = call("get_thread", THREAD_ARGS)
    assert result_of(response)["isError"] is True
    assert "timed out" in text_of(response).lower()


def test_non_json_body_does_not_raise_a_decode_error(monkeypatch):
    transport(monkeypatch, FakeResponse(b"<html>Cloudflare</html>"))
    response = call("get_thread", THREAD_ARGS)
    assert result_of(response)["isError"] is True
    message = text_of(response)
    assert "JSON" in message
    assert "Expecting value" not in message


def test_unknown_id_is_not_found_not_an_index_error(monkeypatch):
    transport(monkeypatch, FakeResponse(b'{"data": []}'))
    response = call("get_thread", THREAD_ARGS)
    assert result_of(response)["isError"] is True
    message = text_of(response)
    assert "not found" in message.lower()
    assert "IndexError" not in message


def test_bad_url_or_id_argument_names_the_argument():
    response = call("get_thread", {"url_or_id": "not a url"})
    assert result_of(response)["isError"] is True
    assert "url_or_id" in text_of(response)


def test_empty_search_result_is_not_an_error(monkeypatch):
    transport(monkeypatch, FakeResponse(b'{"data": []}'))
    response = call("search_posts", {"subreddit": "LoremIpsum"})
    assert result_of(response)["isError"] is False
    assert "No posts" in text_of(response)


def test_server_survives_a_failure_and_answers_the_next_call(monkeypatch, post, comment_tree):
    transport(monkeypatch, lambda: http_error(503, b"down"))
    assert result_of(call("get_thread", THREAD_ARGS))["isError"] is True

    responses = {
        "/api/posts/ids": {"data": [post]},
        "/api/comments/tree": {"data": comment_tree},
    }

    def fake_urlopen(req, timeout=None):
        path = req.full_url.split("?", 1)[0].removeprefix(api.BASE_URL)
        return FakeResponse(json.dumps(responses[path]).encode())

    monkeypatch.setattr(api.request, "urlopen", fake_urlopen)

    response = call("get_thread", THREAD_ARGS)
    assert result_of(response)["isError"] is False
    assert "Dolor sit amet" in text_of(response)


def test_unknown_tool_name_is_a_jsonrpc_method_error():
    response = call("get_nonexistent", {})
    assert response["error"]["code"] == -32601
