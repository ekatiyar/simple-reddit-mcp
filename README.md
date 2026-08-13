# simple-reddit-mcp

[![PyPI](https://img.shields.io/pypi/v/simple-reddit-mcp)](https://pypi.org/project/simple-reddit-mcp/)
[![CI](https://github.com/ekatiyar/simple-reddit-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ekatiyar/simple-reddit-mcp/actions/workflows/ci.yml)

A read-only Reddit MCP server that needs **no Reddit account, no API key, and no
browser**. It reads threads, comments and subreddits from the
[Arctic Shift](https://arctic-shift.photon-reddit.com) archive over plain
keyless HTTP.

One runtime dependency, [`zeromcp`](https://github.com/mrexodia/zeromcp), keeps `simple-reddit-mcp` lightweight and quick to start.

## Requirements

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`

## Run it

```bash
uvx simple-reddit-mcp
```

The server speaks MCP over stdio: JSON-RPC on stdout, logs on stderr.

## Configure your MCP client

Claude:

```bash
claude mcp add reddit --scope user -- uvx simple-reddit-mcp
```

or

```json
{
  "mcpServers": {
    "reddit": {
      "command": "uvx",
      "args": ["simple-reddit-mcp"]
    }
  }
}
```

Codex — in `~/.codex/config.toml`:

```toml
[mcp_servers.reddit]
command = "uvx"
args = ["simple-reddit-mcp"]
```

## Tools

Implemented:

| Tool | Arctic Shift endpoint | Purpose |
|---|---|---|
| `get_thread` | `/api/posts/ids` + `/api/comments/tree` | A post plus its comment tree, from any reddit URL or id |
| `get_posts` | `/api/posts/ids` | Bulk post lookup by id (up to 500) |
| `get_comments` | `/api/comments/ids` | Bulk comment lookup by id (up to 500) |
| `search_posts` | `/api/posts/search` | Discovery by subreddit / keyword / author / date range |
| `search_comments` | `/api/comments/search` | Comment-level search; with `author=` it doubles as user history |
| `search_subreddits` | `/api/subreddits/search` | Find subreddits by name, prefix, size, or age |

Not currently implemented:

| Tool | Arctic Shift endpoint |
|---|---|
| `search_users` | `/api/users/search` |
| `aggregate_posts` / `aggregate_comments` | `/api/{posts,comments}/search/aggregate` |
| `time_series` | `/api/time_series` |
| `subreddit_rules` | `/api/subreddits/rules` |
| `subreddit_wiki` | `/api/subreddits/wikis`, `/api/subreddits/wikis/list` |
| `user_interactions` | `/api/users/interactions/{users,subreddits}`, `.../users/list` |
| `user_flairs` | `/api/users/aggregate_flairs` |
| `resolve_short_link` | `/api/short_links` |
| — | `/api/subreddits/ids`, `/api/users/ids` |

## Caveats

- **Read-only.** Voting, commenting and posting require Reddit auth
- **`score` and `num_comments` are placeholders for ~36h.** Arctic Shift archives
  a post the moment it appears and backfills vote data later, so fresh posts
  report `1` and `0`. Rendered output flags anything under 36h old.
- **Free service = no uptime SLA.**

## Development

```bash
uv sync --group dev
uv run --group dev pytest
```

To publish a new release to PyPI, bump `version` and push to master:

```bash
uv version --bump patch   # bumps pyproject.toml and relocks
git commit -am "release $(uv version --short)"
git push
```

## Attribution

MIT licensed.

- Built on [`zeromcp`](https://github.com/mrexodia/zeromcp) (MIT).
- Data comes from [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift), a free service; be considerate with it.
