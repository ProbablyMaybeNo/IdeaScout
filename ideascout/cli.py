"""IdeaScout CLI.

Subcommands available on Day 1:
  init     — create the DB and sync sources.yaml
  sources  — list configured sources
  poll     — poll every enabled source
  stats    — post counts by source

Day 2-3 subcommands (stubs for now):
  classify, digest
"""
from __future__ import annotations

import argparse
import sys

from ideascout.db import (
    connect,
    count_posts,
    count_posts_by_source,
    init_schema,
    list_enabled_sources,
)
from ideascout.ingest import poll_all
from ideascout.sources_loader import sync_sources_to_db


def cmd_init(_args) -> int:
    conn = connect()
    init_schema(conn)
    n = sync_sources_to_db(conn)
    print(f"Initialized DB. Synced {n} sources from config/sources.yaml.")
    return 0


def cmd_sources(_args) -> int:
    conn = connect()
    init_schema(conn)
    sync_sources_to_db(conn)
    rows = list_enabled_sources(conn)
    if not rows:
        print("No sources configured. Edit config/sources.yaml then run `init`.")
        return 1
    print(f"{len(rows)} enabled source(s):")
    for r in rows:
        last = r["last_polled_at"] or "never"
        print(f"  - [{r['type']:<18}] {r['name']:<30}  last polled: {last}")
    return 0


def cmd_poll(args) -> int:
    conn = connect()
    init_schema(conn)
    sync_sources_to_db(conn)
    print(f"Polling enabled sources...")
    results = poll_all(conn, verbose=not args.quiet)

    total_fetched = sum(r.fetched for r in results)
    total_new = sum(r.inserted for r in results)
    total_dup = sum(r.duplicates for r in results)
    errs = [r for r in results if r.error]

    print()
    print(f"Poll complete: {len(results)} sources, "
          f"{total_fetched} fetched, {total_new} new, {total_dup} duplicates, "
          f"{len(errs)} errors.")
    if errs:
        return 2
    return 0


def cmd_stats(_args) -> int:
    conn = connect()
    init_schema(conn)
    total = count_posts(conn)
    by_src = count_posts_by_source(conn)
    print(f"Total posts in DB: {total}")
    print()
    print(f"{'source':<32} {'type':<18} {'count':>7}")
    print("-" * 60)
    for r in by_src:
        print(f"{r['name']:<32} {r['type']:<18} {r['post_count']:>7}")
    return 0


def cmd_classify(_args) -> int:
    print("classify: not implemented yet — Day 2.", file=sys.stderr)
    return 1


def cmd_digest(_args) -> int:
    print("digest: not implemented yet — Day 3.", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ideascout", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create DB and sync sources").set_defaults(func=cmd_init)
    sub.add_parser("sources", help="list configured sources").set_defaults(func=cmd_sources)

    p_poll = sub.add_parser("poll", help="poll every enabled source")
    p_poll.add_argument("--quiet", "-q", action="store_true")
    p_poll.set_defaults(func=cmd_poll)

    sub.add_parser("stats", help="post counts by source").set_defaults(func=cmd_stats)
    sub.add_parser("classify", help="(Day 2) classify new posts via Ollama").set_defaults(func=cmd_classify)
    sub.add_parser("digest", help="(Day 3) generate weekly markdown digest").set_defaults(func=cmd_digest)

    return p


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(args.func(args))
