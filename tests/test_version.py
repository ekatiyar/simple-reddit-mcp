"""The version lives in pyproject.toml and nowhere else.

A stale literal anywhere in the package makes the stderr banner, the MCP handshake
and the User-Agent disagree about what is running.
"""

import importlib.metadata

import simple_reddit_mcp
from simple_reddit_mcp import api


def test_version_matches_installed_metadata():
    assert simple_reddit_mcp.__version__ == importlib.metadata.version("simple-reddit-mcp")


def test_user_agent_carries_the_package_version():
    assert api.USER_AGENT.startswith(f"simple-reddit-mcp/{simple_reddit_mcp.__version__} ")
