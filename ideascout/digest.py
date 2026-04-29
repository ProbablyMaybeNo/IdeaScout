"""Friday digest generator.

Produces a markdown brief of the week's top demand signals + source/domain
context, persists it to data/digests/{week}.md and to the digests DB table.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ideascout.classifier import load_classifier_config
from ideascout.db import (
    classification_counts_since,
    domain_breakdown_since,
    list_demand_signals,
    post_count_since,
    source_health_since,
    upsert_digest,
)

DEFAULT_DIGEST_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "digests"
)

DEFAULT_TOP_N = 5
DEFAULT_TABLE_LIMIT = 20
HIGH_CONVICTION_THRESHOLD = 15  # of 25
WINDOW_DAYS = 7


@dataclass(slots=True)
class DigestResult:
    week_iso: str
    content_md: str
    output_path: Path
    posts_count: int
    candidates_count: int


def _iso_week(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _format_signal_block(row: sqlite3.Row, rank: int) -> str:
    tags = json.loads(row["domain_tags"] or "[]")
    score = row["total_score"]
    next_move = _suggest_next_move(row)
    posted = row["posted_at"] or row["scraped_at"]
    return (
        f"### {rank}. [{score}/25] {row['summary'] or row['title']}\n\n"
        f"- **Source:** {row['source_name']}  ·  **Posted:** {posted}\n"
        f"- **Title:** {row['title']}\n"
        f"- **Tags:** `{', '.join(tags) or 'none'}`\n"
        f"- **Scores:** urgency `{row['urgency_score']}`  ·  "
        f"buildable `{row['solo_buildable_score']}`  ·  "
        f"pain `{row['workaround_pain']}`  ·  "
        f"pay `{row['payment_evidence']}`  ·  "
        f"niche `{row['niche_specificity']}`\n"
        f"- **Confidence:** {row['demand_confidence']:.2f}\n"
        f"- **Next move:** {next_move}\n"
        f"- **Link:** {row['url']}\n"
    )


def _suggest_next_move(row: sqlite3.Row) -> str:
    """Heuristic next-step pulled from the 5-signal framework."""
    score = row["total_score"]
    pay = row["payment_evidence"]
    niche = row["niche_specificity"]
    buildable = row["solo_buildable_score"]
    if score >= 20:
        return "Drop everything — ship a 1-page landing this week."
    if score >= 17 and pay >= 3 and buildable >= 4:
        return "Worth a 1-2 day MVP. Validate via originating community first."
    if score >= 15 and niche >= 4:
        return "Niche fit is strong. Watch for 2 more independent signals."
    if score >= 12:
        return "Park as candidate; revisit after 2-3 more weeks of data."
    return "Track only."


def _format_domain_table(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "_No demand signals classified into a domain this week._\n"
    lines = ["| Domain | Demand signals | Avg score |", "|---|---:|---:|"]
    for r in rows:
        lines.append(
            f"| `{r['domain']}` | {r['signal_count']} | {r['avg_score']} |"
        )
    return "\n".join(lines) + "\n"


def _format_source_health(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "_No sources enabled._\n"
    lines = [
        "| Source | Posts ingested | Demand signals | Last polled | Status |",
        "|---|---:|---:|---|---|",
    ]
    for r in rows:
        last = r["last_polled_at"] or "never"
        status = "OK" if not r["last_error"] else f"err: {(r['last_error'] or '')[:40]}"
        lines.append(
            f"| {r['source_name']} | {r['posts_in_window']} | "
            f"{r['signals_in_window'] or 0} | {last} | {status} |"
        )
    return "\n".join(lines) + "\n"


def _format_full_signal_table(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "_No demand signals this week._\n"
    lines = ["| Score | Title | Source | Tags |", "|---:|---|---|---|"]
    for r in rows:
        tags = json.loads(r["domain_tags"] or "[]")
        title = (r["title"] or "")[:60].replace("|", "\\|")
        lines.append(
            f"| {r['total_score']} | "
            f"[{title}]({r['url']}) | {r['source_name']} | "
            f"`{', '.join(tags)}` |"
        )
    return "\n".join(lines) + "\n"


def generate_digest(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    top_n: int = DEFAULT_TOP_N,
    table_limit: int = DEFAULT_TABLE_LIMIT,
    output_dir: Path = DEFAULT_DIGEST_DIR,
    write_file: bool = True,
) -> DigestResult:
    cfg = load_classifier_config()
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    since_iso = since.isoformat()

    posts_count = post_count_since(conn, since_iso)
    counts = classification_counts_since(conn, cfg.version, since_iso)

    signals_top = list_demand_signals(
        conn,
        cfg.version,
        min_confidence=0.5,
        limit=top_n,
        since_iso=since_iso,
    )
    signals_table = list_demand_signals(
        conn,
        cfg.version,
        min_confidence=0.5,
        limit=table_limit,
        since_iso=since_iso,
    )
    domain_rows = domain_breakdown_since(conn, cfg.version, since_iso)
    source_rows = source_health_since(conn, cfg.version, since_iso)

    week_iso = _iso_week(now)

    parts: list[str] = []
    parts.append(f"# IdeaScout Weekly Digest — {week_iso}\n")
    parts.append(
        f"_Generated {now.strftime('%Y-%m-%d %H:%M UTC')} · "
        f"window: last {WINDOW_DAYS} days · classifier {cfg.version}_\n"
    )

    parts.append("## Executive summary\n")
    if counts["demand"] == 0:
        parts.append(
            "_No demand signals surfaced this week._ "
            "Either the corpus is too small (let it accumulate) or the "
            "intent-phrase filters are too tight for current source mix.\n"
        )
    else:
        parts.append(
            f"- **{posts_count}** posts ingested in the last {WINDOW_DAYS} days\n"
            f"- **{counts['classified']}** classified at version {cfg.version}\n"
            f"- **{counts['demand']}** demand signals identified "
            f"({counts['high_conviction']} high-conviction, score ≥{HIGH_CONVICTION_THRESHOLD}/25)\n"
        )
    parts.append("")

    parts.append("## Top candidates\n")
    if not signals_top:
        parts.append("_Nothing scored highly enough to surface this week._\n")
    else:
        for rank, row in enumerate(signals_top, 1):
            parts.append(_format_signal_block(row, rank))

    parts.append("## Domain breakdown\n")
    parts.append(_format_domain_table(domain_rows))

    parts.append("## Source health (last 7 days)\n")
    parts.append(_format_source_health(source_rows))

    parts.append(
        f"## All demand signals this week (top {min(table_limit, len(signals_table))})\n"
    )
    parts.append(_format_full_signal_table(signals_table))

    parts.append("---\n")
    parts.append(
        "_The next-move heuristics are guidance, not gospel. "
        "Always validate before committing build time._\n"
    )

    content_md = "\n".join(parts)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{week_iso}.md"
    if write_file:
        output_path.write_text(content_md, encoding="utf-8")

    upsert_digest(
        conn,
        week_iso=week_iso,
        content_md=content_md,
        posts_count=posts_count,
        candidates_count=counts["demand"],
    )

    return DigestResult(
        week_iso=week_iso,
        content_md=content_md,
        output_path=output_path,
        posts_count=posts_count,
        candidates_count=counts["demand"],
    )
