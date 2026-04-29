import json
from datetime import datetime, timezone

from ideascout.db import (
    insert_classification,
    insert_post_if_new,
    upsert_source,
)
from ideascout.digest import generate_digest, _suggest_next_move
from ideascout.models import RawPost


def _seed_post(conn, source_id, *, ext_id, title, body=""):
    post = RawPost(
        external_id=ext_id,
        title=title,
        url=f"https://example.com/{ext_id}",
        body=body,
        posted_at=datetime.now(timezone.utc),
    )
    insert_post_if_new(conn, source_id, post)
    cur = conn.execute(
        "SELECT id FROM posts WHERE source_id = ? AND external_id = ?",
        (source_id, ext_id),
    )
    return cur.fetchone()["id"]


def _seed_classification(conn, post_id, *, version="v1.0", **overrides):
    row = {
        "is_demand_signal": 1,
        "demand_confidence": 0.7,
        "signal_type": "asking_for_tool",
        "domain_tags": json.dumps(["tabletop_gaming"]),
        "urgency_score": 4,
        "solo_buildable_score": 4,
        "workaround_pain": 3,
        "payment_evidence": 2,
        "niche_specificity": 5,
        "summary": "User wants paint inventory tracker.",
    }
    row.update(overrides)
    insert_classification(conn, post_id=post_id, classifier_version=version, row=row)


def test_generate_digest_smoke(db, tmp_path):
    sid = upsert_source(db, "r/test", "reddit", {"subreddit": "test"}, enabled=True)
    pid = _seed_post(db, sid, ext_id="abc", title="Need a tool to track paints")
    _seed_classification(db, pid)

    output_dir = tmp_path / "digests"
    from ideascout import digest as digest_mod
    digest_mod.DEFAULT_DIGEST_DIR = output_dir

    result = generate_digest(db, output_dir=output_dir)
    assert result.posts_count == 1
    assert result.candidates_count == 1
    assert result.output_path.exists()
    body = result.output_path.read_text(encoding="utf-8")
    assert "IdeaScout Weekly Digest" in body
    assert "Need a tool to track paints" in body
    assert "tabletop_gaming" in body


def test_generate_digest_handles_no_signals(db, tmp_path):
    sid = upsert_source(db, "r/test", "reddit", {"subreddit": "test"}, enabled=True)
    pid = _seed_post(db, sid, ext_id="abc", title="Just a discussion")
    _seed_classification(
        db, pid, is_demand_signal=0, demand_confidence=0.0, urgency_score=1
    )
    output_dir = tmp_path / "digests"
    result = generate_digest(db, output_dir=output_dir)
    assert result.candidates_count == 0
    body = result.output_path.read_text(encoding="utf-8")
    assert "No demand signals" in body or "Nothing scored" in body


def test_suggest_next_move_progression():
    base = {
        "total_score": 21,
        "payment_evidence": 4,
        "niche_specificity": 5,
        "solo_buildable_score": 5,
    }
    assert "Drop everything" in _suggest_next_move(base)
    assert "1-2 day MVP" in _suggest_next_move({**base, "total_score": 17})
    assert "Niche fit" in _suggest_next_move({**base, "total_score": 15, "payment_evidence": 1})
    assert "Park" in _suggest_next_move({**base, "total_score": 12, "niche_specificity": 2})
    assert "Track only" in _suggest_next_move({**base, "total_score": 5, "niche_specificity": 1})
