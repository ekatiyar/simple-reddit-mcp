import json
import re

from simple_reddit_mcp import render


def indent_of(text: str, needle: str) -> int:
    for line in text.splitlines():
        if needle in line:
            return len(line) - len(line.lstrip(" "))
    raise AssertionError(f"{needle!r} not found in output")


def test_post_header_carries_the_essentials(post, comment_tree):
    out = render.render_thread(post, comment_tree)
    assert "Dolor sit amet: a synthetic thread for tests" in out
    assert "ipsum_user_01" in out
    assert "512" in out
    assert "7 comments" in out
    assert "r/LoremIpsum" in out
    assert "/r/LoremIpsum/comments/p0stid1/dolor_sit_amet/" in out


def test_nesting_comes_from_recursion_not_the_wire_depth(post, comment_tree):
    # Fixture comments carry "depth": null, so indentation must come from recursion.
    def walk(nodes):
        for node in nodes:
            if node["kind"] == "t1":
                assert node["data"]["depth"] is None
                replies = node["data"]["replies"]
                if isinstance(replies, dict):
                    walk(replies["data"]["children"])

    walk(comment_tree)

    out = render.render_thread(post, comment_tree)
    top = indent_of(out, "Lorem ipsum dolor sit amet. Consectetur")
    second = indent_of(out, "Sed do eiusmod tempor incididunt ut labore.")
    third = indent_of(out, "Ut enim ad minim veniam")
    assert top < second < third


def test_more_node_renders_a_collapsed_marker(post, comment_tree):
    out = render.render_thread(post, comment_tree)
    assert "_[+6 more replies]_" in out


def test_deleted_comment_with_null_author_does_not_crash(post, comment_tree):
    out = render.render_thread(post, comment_tree)
    assert "[deleted]" in out


def test_long_body_is_truncated_without_breaking_the_tree(post, comment_tree):
    out = render.render_thread(post, comment_tree)
    assert "[body truncated]" in out
    assert "Lorem ipsum dolor sit amet. Consectetur" in out
    assert "_[+6 more replies]_" in out
    long_line = next(line for line in out.splitlines() if "[body truncated]" in line)
    assert len(long_line) < 2000


def test_max_chars_budget_is_honoured(post, comment_tree):
    out = render.render_thread(post, comment_tree, max_chars=2000)
    assert len(out) <= 2000
    tail = out.splitlines()[-1]
    assert "truncated" in tail
    assert "comment_limit" in tail
    assert "max_chars" in tail


def test_sort_top_orders_top_level_comments_by_score(post, comment_tree):
    default = render.render_thread(post, comment_tree)
    sorted_out = render.render_thread(post, comment_tree, sort_top=True)

    def order(text):
        found = []
        for line in text.splitlines():
            for author in ("ipsum_user_02", "ipsum_user_05"):
                if author in line and not line.startswith(" "):
                    found.append(author)
        return found

    assert order(default) == ["ipsum_user_02", "ipsum_user_05"]
    assert order(sorted_out) == ["ipsum_user_05", "ipsum_user_02"]


def test_render_thread_without_a_post(comment_tree):
    out = render.render_thread(None, comment_tree)
    assert "ipsum_user_02" in out


def test_render_posts(search_posts):
    out = render.render_posts(search_posts)
    assert "Consectetur adipiscing elit" in out
    assert "ipsum_user_06" in out
    assert "s3archp1" in out
    assert out.count("\n") < 60


def test_render_posts_budget_names_limit(search_posts):
    out = render.render_posts(search_posts, max_chars=300)
    assert len(out) <= 300
    assert "limit" in out.splitlines()[-1]


def test_render_comments(comment_tree):
    flat = [node["data"] for node in comment_tree]
    out = render.render_comments(flat)
    assert "ipsum_user_02" in out
    assert "r/LoremIpsum" in out


def test_render_subreddits(search_subreddits):
    out = render.render_subreddits(search_subreddits)
    assert "r/LoremIpsum" in out
    assert "328,652" in out or "328652" in out


def test_render_raw_is_parseable(post, comment_tree):
    out = render.render_raw({"post": post, "comments": comment_tree})
    assert json.loads(out)["post"]["id"] == "p0stid1"


def test_render_raw_truncates_loudly():
    out = render.render_raw({"pad": "x" * 5000}, max_chars=500)
    assert len(out) <= 500
    assert "truncated" in out


def test_empty_results_are_explicit():
    assert "No " in render.render_posts([])
    assert "No " in render.render_comments([])
    assert "No " in render.render_subreddits([])


def test_scores_under_36h_carry_a_freshness_note(post):
    fresh = dict(post, score=1, num_comments=0, created_utc=int(render.now()) - 3600)
    out = render.render_thread(fresh, [])
    assert re.search(r"not.*(backfill|final|reliable)", out, re.I)
