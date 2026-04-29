"""SQLite schema and queries.

Single-tenant for now; the schema is multi-tenant-ready (we just don't add a
`user_id` column yet — adding it later is a one-migration change).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ideascout.models import RawPost, utcnow

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ideascout.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id              INTEGER PRIMARY KEY,
  name            TEXT UNIQUE NOT NULL,
  type            TEXT NOT NULL,
  config_json     TEXT NOT NULL,
  enabled         INTEGER NOT NULL DEFAULT 1,
  last_polled_at  TEXT,
  last_error      TEXT
);

CREATE TABLE IF NOT EXISTS posts (
  id            INTEGER PRIMARY KEY,
  source_id     INTEGER NOT NULL REFERENCES sources(id),
  external_id   TEXT NOT NULL,
  title         TEXT NOT NULL,
  body          TEXT NOT NULL DEFAULT '',
  author        TEXT,
  url           TEXT NOT NULL,
  posted_at     TEXT,
  scraped_at    TEXT NOT NULL DEFAULT (datetime('now')),
  raw_json      TEXT,
  UNIQUE (source_id, external_id)
);

CREATE TABLE IF NOT EXISTS classifications (
  id                    INTEGER PRIMARY KEY,
  post_id               INTEGER NOT NULL REFERENCES posts(id),
  classifier_version    TEXT NOT NULL,
  is_demand_signal      INTEGER NOT NULL,
  demand_confidence     REAL NOT NULL,
  signal_type           TEXT,
  domain_tags           TEXT,
  urgency_score         INTEGER,
  solo_buildable_score  INTEGER,
  workaround_pain       INTEGER,
  payment_evidence      INTEGER,
  niche_specificity     INTEGER,
  summary               TEXT,
  classified_at         TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (post_id, classifier_version)
);

CREATE TABLE IF NOT EXISTS candidates (
  id              INTEGER PRIMARY KEY,
  theme           TEXT NOT NULL,
  description     TEXT,
  post_ids_json   TEXT NOT NULL,
  confidence      REAL,
  status          TEXT NOT NULL DEFAULT 'new',
  notes           TEXT,
  first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
  user_priority   INTEGER
);

CREATE TABLE IF NOT EXISTS digests (
  id                INTEGER PRIMARY KEY,
  week_iso          TEXT NOT NULL UNIQUE,
  content_md        TEXT NOT NULL,
  generated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  posts_count       INTEGER,
  candidates_count  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_posts_source_posted ON posts(source_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_scraped       ON posts(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_classifications_post ON classifications(post_id);
CREATE INDEX IF NOT EXISTS idx_classifications_demand
    ON classifications(is_demand_signal, urgency_score);
"""


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# ---------- sources ----------

def upsert_source(
    conn: sqlite3.Connection, name: str, type_: str, config: dict, enabled: bool
) -> int:
    cfg_json = json.dumps(config, sort_keys=True)
    cur = conn.execute(
        """
        INSERT INTO sources (name, type, config_json, enabled)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            type = excluded.type,
            config_json = excluded.config_json,
            enabled = excluded.enabled
        RETURNING id
        """,
        (name, type_, cfg_json, 1 if enabled else 0),
    )
    row = cur.fetchone()
    conn.commit()
    return row["id"]


def list_enabled_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT id, name, type, config_json, last_polled_at FROM sources WHERE enabled = 1 ORDER BY id"
    )
    return list(cur.fetchall())


def mark_source_polled(
    conn: sqlite3.Connection, source_id: int, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE sources SET last_polled_at = ?, last_error = ? WHERE id = ?",
        (utcnow().isoformat(), error, source_id),
    )
    conn.commit()


# ---------- posts ----------

def insert_post_if_new(
    conn: sqlite3.Connection, source_id: int, post: RawPost
) -> bool:
    """Return True if inserted, False if it was a duplicate."""
    posted_at_iso = post.posted_at.isoformat() if post.posted_at else None
    raw_json = json.dumps(post.raw_payload, default=str) if post.raw_payload else None
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO posts
            (source_id, external_id, title, body, author, url, posted_at, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            post.external_id,
            post.title,
            post.body,
            post.author,
            post.url,
            posted_at_iso,
            raw_json,
        ),
    )
    inserted = cur.rowcount > 0
    if inserted:
        conn.commit()
    return inserted


def count_posts(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) AS n FROM posts")
    return int(cur.fetchone()["n"])


def count_posts_by_source(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT s.name, s.type, COUNT(p.id) AS post_count
        FROM sources s
        LEFT JOIN posts p ON p.source_id = s.id
        GROUP BY s.id
        ORDER BY post_count DESC
        """
    )
    return list(cur.fetchall())


def iter_posts_since(
    conn: sqlite3.Connection, since: datetime
) -> Iterator[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM posts WHERE scraped_at >= ? ORDER BY scraped_at",
        (since.isoformat(),),
    )
    yield from cur


# ---------- classifications ----------

def list_unclassified_posts(
    conn: sqlite3.Connection, classifier_version: str, limit: int | None = None
) -> list[sqlite3.Row]:
    """Return posts that have no classification at the given version."""
    sql = """
        SELECT p.id, p.title, p.body, p.url, s.name AS source_name
        FROM posts p
        JOIN sources s ON s.id = p.source_id
        WHERE NOT EXISTS (
            SELECT 1 FROM classifications c
            WHERE c.post_id = p.id AND c.classifier_version = ?
        )
        ORDER BY p.scraped_at DESC
    """
    params: tuple = (classifier_version,)
    if limit is not None:
        sql += " LIMIT ?"
        params = (classifier_version, limit)
    cur = conn.execute(sql, params)
    return list(cur.fetchall())


def insert_classification(
    conn: sqlite3.Connection,
    *,
    post_id: int,
    classifier_version: str,
    row: dict,
) -> int:
    cur = conn.execute(
        """
        INSERT OR REPLACE INTO classifications
            (post_id, classifier_version,
             is_demand_signal, demand_confidence, signal_type, domain_tags,
             urgency_score, solo_buildable_score,
             workaround_pain, payment_evidence, niche_specificity,
             summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            post_id,
            classifier_version,
            row["is_demand_signal"],
            row["demand_confidence"],
            row["signal_type"],
            row["domain_tags"],
            row["urgency_score"],
            row["solo_buildable_score"],
            row["workaround_pain"],
            row["payment_evidence"],
            row["niche_specificity"],
            row["summary"],
        ),
    )
    conn.commit()
    return cur.lastrowid or 0


def count_classifications(conn: sqlite3.Connection, classifier_version: str) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) AS n FROM classifications WHERE classifier_version = ?",
        (classifier_version,),
    )
    return int(cur.fetchone()["n"])


def list_demand_signals(
    conn: sqlite3.Connection,
    classifier_version: str,
    *,
    min_confidence: float = 0.5,
    limit: int = 50,
    since_iso: str | None = None,
) -> list[sqlite3.Row]:
    sql = """
        SELECT
            p.id, p.title, p.url, p.body, p.posted_at, p.scraped_at,
            s.name AS source_name,
            c.demand_confidence, c.signal_type, c.domain_tags,
            c.urgency_score, c.solo_buildable_score,
            c.workaround_pain, c.payment_evidence, c.niche_specificity,
            c.summary,
            (c.urgency_score + c.solo_buildable_score
             + c.workaround_pain + c.payment_evidence + c.niche_specificity)
                AS total_score
        FROM classifications c
        JOIN posts p ON p.id = c.post_id
        JOIN sources s ON s.id = p.source_id
        WHERE c.classifier_version = ?
          AND c.is_demand_signal = 1
          AND c.demand_confidence >= ?
    """
    params: list = [classifier_version, min_confidence]
    if since_iso is not None:
        sql += " AND p.scraped_at >= ?"
        params.append(since_iso)
    sql += " ORDER BY total_score DESC, c.demand_confidence DESC LIMIT ?"
    params.append(limit)
    cur = conn.execute(sql, params)
    return list(cur.fetchall())


def post_count_since(conn: sqlite3.Connection, since_iso: str) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) AS n FROM posts WHERE scraped_at >= ?",
        (since_iso,),
    )
    return int(cur.fetchone()["n"])


def classification_counts_since(
    conn: sqlite3.Connection, classifier_version: str, since_iso: str
) -> dict:
    cur = conn.execute(
        """
        SELECT
            COUNT(*) AS classified,
            SUM(CASE WHEN c.is_demand_signal = 1 THEN 1 ELSE 0 END) AS demand,
            SUM(CASE WHEN c.is_demand_signal = 1
                      AND (c.urgency_score + c.solo_buildable_score
                           + c.workaround_pain + c.payment_evidence
                           + c.niche_specificity) >= 15
                     THEN 1 ELSE 0 END) AS high_conviction
        FROM classifications c
        JOIN posts p ON p.id = c.post_id
        WHERE c.classifier_version = ?
          AND p.scraped_at >= ?
        """,
        (classifier_version, since_iso),
    )
    row = cur.fetchone()
    return {
        "classified": int(row["classified"] or 0),
        "demand": int(row["demand"] or 0),
        "high_conviction": int(row["high_conviction"] or 0),
    }


def domain_breakdown_since(
    conn: sqlite3.Connection, classifier_version: str, since_iso: str
) -> list[sqlite3.Row]:
    """Per-domain count of demand signals + average total score in window."""
    cur = conn.execute(
        """
        SELECT
            je.value AS domain,
            COUNT(*) AS signal_count,
            ROUND(AVG(
                c.urgency_score + c.solo_buildable_score
                + c.workaround_pain + c.payment_evidence + c.niche_specificity
            ), 1) AS avg_score
        FROM classifications c
        JOIN posts p ON p.id = c.post_id
        JOIN json_each(c.domain_tags) je
        WHERE c.classifier_version = ?
          AND c.is_demand_signal = 1
          AND p.scraped_at >= ?
        GROUP BY je.value
        ORDER BY signal_count DESC, avg_score DESC
        """,
        (classifier_version, since_iso),
    )
    return list(cur.fetchall())


def source_health_since(
    conn: sqlite3.Connection, classifier_version: str, since_iso: str
) -> list[sqlite3.Row]:
    """Per-source posts scraped + demand signals in window + last_polled_at."""
    cur = conn.execute(
        """
        SELECT
            s.name AS source_name,
            s.type AS source_type,
            s.last_polled_at,
            s.last_error,
            COUNT(p.id) AS posts_in_window,
            SUM(CASE WHEN c.is_demand_signal = 1 THEN 1 ELSE 0 END) AS signals_in_window
        FROM sources s
        LEFT JOIN posts p
               ON p.source_id = s.id AND p.scraped_at >= ?
        LEFT JOIN classifications c
               ON c.post_id = p.id AND c.classifier_version = ?
        WHERE s.enabled = 1
        GROUP BY s.id
        ORDER BY signals_in_window DESC, posts_in_window DESC
        """,
        (since_iso, classifier_version),
    )
    return list(cur.fetchall())


def upsert_digest(
    conn: sqlite3.Connection,
    *,
    week_iso: str,
    content_md: str,
    posts_count: int,
    candidates_count: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO digests (week_iso, content_md, posts_count, candidates_count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(week_iso) DO UPDATE SET
            content_md = excluded.content_md,
            generated_at = datetime('now'),
            posts_count = excluded.posts_count,
            candidates_count = excluded.candidates_count
        RETURNING id
        """,
        (week_iso, content_md, posts_count, candidates_count),
    )
    row = cur.fetchone()
    conn.commit()
    return int(row["id"])


def get_latest_digest(conn: sqlite3.Connection) -> sqlite3.Row | None:
    cur = conn.execute(
        "SELECT * FROM digests ORDER BY generated_at DESC LIMIT 1"
    )
    return cur.fetchone()
