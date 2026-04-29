"""Adapter contract tests. Network-dependent — marked live, skipped by default.

Run with: py -3.13 -m pytest -m live tests/test_adapters.py
"""
import pytest

from ideascout.adapters import get_adapter


live = pytest.mark.skipif(
    "not config.getoption('-m') or 'live' not in config.getoption('-m')",
    reason="network-dependent; run with -m live",
)


def test_registry_has_day1_adapters():
    for name in ("reddit", "hackernews", "rss"):
        a = get_adapter(name)
        assert a.type_name == name


def test_registry_has_day4_adapters():
    for name in ("pulsemcp", "github_trending", "ycombinator"):
        a = get_adapter(name)
        assert a.type_name == name


def test_registry_unknown_raises():
    with pytest.raises(KeyError):
        get_adapter("not-a-real-type")


@live
def test_reddit_live_smoke():
    adapter = get_adapter("reddit")
    posts = adapter.poll({"subreddit": "test", "limit": 5, "intent_phrases": []})
    assert isinstance(posts, list)


@live
def test_hackernews_live_smoke():
    adapter = get_adapter("hackernews")
    posts = adapter.poll({"query_type": "front_page", "limit": 5})
    assert isinstance(posts, list)
    assert len(posts) >= 1
