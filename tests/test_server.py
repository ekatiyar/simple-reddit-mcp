"""Round-trip the real console script over stdio, in a subprocess.

Offline: the only tools/call made here fails on argument parsing, before any
HTTP request is attempted.
"""

import json
import shutil
import subprocess
import sys

import pytest

TOOL_NAMES = {
    "get_thread", "get_posts", "get_comments",
    "search_posts", "search_comments", "search_subreddits",
}

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


def command():
    script = shutil.which("simple-reddit-mcp")
    if script:
        return [script]
    return [sys.executable, "-m", "simple_reddit_mcp.server"]


@pytest.fixture(scope="module")
def session():
    """Drive one server process with a batch of requests; return (stdout, stderr)."""
    requests = [
        INITIALIZE,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "no/such/method"},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "get_thread", "arguments": {"url_or_id": "not a url"}}},
    ]
    stdin = "".join(json.dumps(request) + "\n" for request in requests)
    completed = subprocess.run(
        command(), input=stdin, capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return completed


def responses_by_id(session):
    return {
        message["id"]: message
        for message in (json.loads(line) for line in session.stdout.splitlines())
    }


def test_stdout_carries_only_jsonrpc(session):
    lines = session.stdout.splitlines()
    assert lines
    for line in lines:
        message = json.loads(line)
        assert message["jsonrpc"] == "2.0"
    # The server logs to stderr; that must not pollute the transport.
    assert session.stderr.strip()


def test_initialize_echoes_protocol_and_advertises_tools(session):
    result = responses_by_id(session)[1]["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "reddit"


def test_notification_produces_no_response(session):
    # Five requests went in, one of them a notification: four responses come out.
    assert len(session.stdout.splitlines()) == 4


def test_tools_list_has_exactly_the_six_tools(session):
    tools = responses_by_id(session)[2]["result"]["tools"]
    assert len(tools) == 6
    assert {tool["name"] for tool in tools} == TOOL_NAMES
    for tool in tools:
        assert tool["description"].strip()
        assert tool["inputSchema"]["type"] == "object"


def test_get_thread_requires_url_or_id(session):
    tools = responses_by_id(session)[2]["result"]["tools"]
    schema = next(tool for tool in tools if tool["name"] == "get_thread")["inputSchema"]
    assert schema["required"] == ["url_or_id"]
    assert "comment_limit" in schema["properties"]


def test_tool_descriptions_carry_the_freshness_caveat(session):
    tools = responses_by_id(session)[2]["result"]["tools"]
    for tool in tools:
        assert "36" in tool["description"], tool["name"]


def test_unknown_method_is_32601(session):
    assert responses_by_id(session)[3]["error"]["code"] == -32601


def test_tools_call_returns_text_content(session):
    result = responses_by_id(session)[4]["result"]
    assert result["content"][0]["type"] == "text"
    assert result["isError"] is True
