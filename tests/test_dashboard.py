import json
from datetime import datetime, timezone

from ideascout.dashboard import generate_dashboard
from ideascout.db import (
    insert_classification,
    insert_post_if_new,
    upsert_source,
)
from ideascout.models import RawPost


def _seed(conn):
    sid = upsert_source(conn, "r/test", "reddit", {"subreddit": "test"}, enabled=True)
    post = RawPost(
        external_id="x",
        title="Need a tool",
        url="https://example.com/x",
        body="we manually do this",
        posted_at=datetime.now(timezone.utc),
    )
    insert_post_if_new(conn, sid, post)
    pid = conn.execute(
        "SELECT id FROM posts WHERE external_id='x'"
    ).fetchone()["id"]
    insert_classification(
        conn,
        post_id=pid,
        classifier_version="v1.0",
        row={
            "is_demand_signal": 1,
            "demand_confidence": 0.8,
            "signal_type": "asking_for_tool",
            "domain_tags": json.dumps(["tabletop_gaming", "ai_builders"]),
            "urgency_score": 4,
            "solo_buildable_score": 5,
            "workaround_pain": 3,
            "payment_evidence": 2,
            "niche_specificity": 5,
            "summary": "wants tracker.",
        },
    )


def test_generate_dashboard_smoke(db, tmp_path):
    _seed(db)
    out = tmp_path / "dashboard.html"
    result = generate_dashboard(db, output_path=out)
    assert result.output_path == out
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "<!doctype html>" in body
    assert "IdeaScout Dashboard" in body
    assert "Need a tool" in body
    assert "tabletop_gaming" in body
    # vanilla JS filter included
    assert "document.getElementById" in body


def test_generate_dashboard_handles_empty(db, tmp_path):
    out = tmp_path / "empty.html"
    result = generate_dashboard(db, output_path=out)
    body = out.read_text(encoding="utf-8")
    assert "<!doctype html>" in body
    assert result.signals_in_window == 0
    assert "No demand signals" in body or "no demand signals" in body.lower()
