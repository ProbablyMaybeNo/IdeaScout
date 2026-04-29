from datetime import datetime, timezone

from ideascout.db import (
    count_posts,
    count_posts_by_source,
    insert_post_if_new,
    list_enabled_sources,
    upsert_source,
)
from ideascout.models import RawPost


def test_upsert_source_creates_then_updates(db):
    sid = upsert_source(db, "r/test", "reddit", {"subreddit": "test"}, enabled=True)
    assert sid > 0
    sid2 = upsert_source(db, "r/test", "reddit", {"subreddit": "test", "limit": 10}, enabled=True)
    assert sid == sid2


def test_list_enabled_sources_filters_disabled(db):
    upsert_source(db, "a", "reddit", {}, enabled=True)
    upsert_source(db, "b", "reddit", {}, enabled=False)
    upsert_source(db, "c", "hackernews", {}, enabled=True)
    rows = list_enabled_sources(db)
    names = {r["name"] for r in rows}
    assert names == {"a", "c"}


def test_insert_post_if_new_dedupes(db):
    sid = upsert_source(db, "src", "reddit", {}, enabled=True)
    post = RawPost(
        external_id="abc",
        title="Hello",
        url="https://example.com/abc",
        body="body",
        posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert insert_post_if_new(db, sid, post) is True
    assert insert_post_if_new(db, sid, post) is False
    assert count_posts(db) == 1


def test_count_posts_by_source_returns_zero_for_empty(db):
    upsert_source(db, "empty-source", "reddit", {}, enabled=True)
    rows = count_posts_by_source(db)
    assert any(r["name"] == "empty-source" and r["post_count"] == 0 for r in rows)
