import pytest

from simple_reddit_mcp import urls

POST_URL = "https://www.reddit.com/r/LoremIpsum/comments/abc123x/dolor_sit_amet/"

CASES = [
    (POST_URL, ("t3_abc123x", None)),
    (POST_URL.rstrip("/"), ("t3_abc123x", None)),
    (POST_URL + "?utm_source=share&utm_medium=web", ("t3_abc123x", None)),
    (POST_URL + "c0mm3nt", ("t3_abc123x", "t1_c0mm3nt")),
    (POST_URL + "c0mm3nt/?context=3", ("t3_abc123x", "t1_c0mm3nt")),
    ("https://old.reddit.com/r/LoremIpsum/comments/abc123x/", ("t3_abc123x", None)),
    ("https://www.reddit.com/comments/abc123x", ("t3_abc123x", None)),
    ("/r/LoremIpsum/comments/abc123x/dolor_sit_amet/", ("t3_abc123x", None)),
    ("https://redd.it/abc123x", ("t3_abc123x", None)),
    ("abc123x", ("t3_abc123x", None)),
    ("t3_abc123x", ("t3_abc123x", None)),
    ("t1_c0mm3nt", (None, "t1_c0mm3nt")),
    ("  t3_abc123x  ", ("t3_abc123x", None)),
]


@pytest.mark.parametrize("value,expected", CASES)
def test_parse_target(value, expected):
    assert urls.parse_target(value) == expected


@pytest.mark.parametrize("value", ["", "   ", "not a url", "https://example.com/x",
                                   "https://www.reddit.com/r/LoremIpsum/"])
def test_parse_target_rejects_junk(value):
    with pytest.raises(ValueError) as excinfo:
        urls.parse_target(value)
    message = str(excinfo.value)
    assert "url_or_id" in message
    assert "reddit.com" in message


SHORT_LINK_RESPONSE = [
    {
        "original_path": "/r/LoremIpsum/s/L0remSh4re",
        "resolved_path": (
            "/r/LoremIpsum/comments/abc123x/dolor_sit_amet/c0mm3nt"
            "?share_id=L0remSh4reId&utm_medium=android_app&utm_source=share"
        ),
        "found_in": "t1_f0undin1",
        "found_in_thing_created_utc": 1780000000,
        "retrieved_on": 1780100000,
    }
]


@pytest.mark.parametrize("value", [
    "https://www.reddit.com/r/LoremIpsum/s/L0remSh4re",
    "/r/LoremIpsum/s/L0remSh4re",
])
def test_share_link_resolves_through_short_links(value, stub_api):
    calls = stub_api(lambda path, params: SHORT_LINK_RESPONSE)

    assert urls.parse_target(value) == ("t3_abc123x", "t1_c0mm3nt")

    assert calls == [("/api/short_links", {"paths": "/r/LoremIpsum/s/L0remSh4re"})]


def test_share_link_not_in_archive(stub_api):
    stub_api(lambda path, params: [])
    with pytest.raises(ValueError) as excinfo:
        urls.parse_target("https://www.reddit.com/r/LoremIpsum/s/L0remSh4re")
    assert "share link" in str(excinfo.value).lower()


@pytest.mark.parametrize("value,kind,expected", [
    ("abc123x", "t3", "t3_abc123x"),
    ("t3_abc123x", "t3", "t3_abc123x"),
    ("c0mm3nt", "t1", "t1_c0mm3nt"),
    ("t1_c0mm3nt", "t1", "t1_c0mm3nt"),
    ("T3_ABC123X", "t3", "t3_abc123x"),
])
def test_normalize_id(value, kind, expected):
    assert urls.normalize_id(value, kind) == expected


def test_normalize_id_rejects_wrong_prefix():
    with pytest.raises(ValueError):
        urls.normalize_id("t1_c0mm3nt", "t3")


def test_normalize_ids_takes_a_comma_separated_list():
    assert urls.normalize_ids("abc123x, t3_def456y", "t3") == "t3_abc123x,t3_def456y"


def test_normalize_ids_rejects_over_500():
    with pytest.raises(ValueError) as excinfo:
        urls.normalize_ids(",".join(f"abc{n:04d}" for n in range(501)), "t3")
    assert "500" in str(excinfo.value)
