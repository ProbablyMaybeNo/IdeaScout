"""IdeaScout CLI.

Subcommands:
  init      — create the DB and sync sources.yaml
  sources   — list configured sources
  poll      — poll every enabled source
  classify  — score unclassified posts via local Ollama
  signals   — show top demand signals from current classifications
  stats     — post counts by source
  digest    — (Day 3) generate weekly markdown digest
"""
from __future__ import annotations

import argparse
import json
import sys

from ideascout.classifier import (
    ClassifierError,
    OllamaClassifier,
    load_classifier_config,
)
from ideascout.db import (
    connect,
    count_classifications,
    count_posts,
    count_posts_by_source,
    init_schema,
    insert_classification,
    list_demand_signals,
    list_enabled_sources,
    list_unclassified_posts,
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


def cmd_classify(args) -> int:
    conn = connect()
    init_schema(conn)
    sync_sources_to_db(conn)

    cfg = load_classifier_config()
    classifier = OllamaClassifier(cfg)

    print(f"Classifier {cfg.version} model={cfg.model} url={cfg.ollama_url}")
    if not classifier.healthcheck():
        print(
            f"  [fail] Ollama unreachable or model {cfg.model!r} not pulled. "
            f"Run `ollama serve` and `ollama pull {cfg.model}`.",
            file=sys.stderr,
        )
        return 2

    pending = list_unclassified_posts(conn, cfg.version, limit=args.limit)
    if not pending:
        print("Nothing to classify.")
        return 0

    print(f"Classifying {len(pending)} post(s)...")
    ok = 0
    failed = 0
    for i, row in enumerate(pending, 1):
        title = row["title"]
        try:
            result = classifier.classify_post(
                source_name=row["source_name"],
                title=title,
                body=row["body"] or "",
            )
            insert_classification(
                conn,
                post_id=row["id"],
                classifier_version=cfg.version,
                row=result.to_db_row(),
            )
            ok += 1
            if not args.quiet:
                tag = "DEMAND" if result.is_demand_signal else "skip  "
                conf = f"{result.demand_confidence:.2f}"
                print(
                    f"  [{i}/{len(pending)}] {tag} conf={conf} u={result.urgency_score} "
                    f"b={result.solo_buildable_score} | {title[:80]}"
                )
        except ClassifierError as e:
            failed += 1
            print(
                f"  [{i}/{len(pending)}] ERROR {e}: {title[:80]}",
                file=sys.stderr,
            )

    total = count_classifications(conn, cfg.version)
    print()
    print(
        f"Classify complete: {ok} ok, {failed} failed. "
        f"Total at version {cfg.version}: {total}."
    )
    return 0 if failed == 0 else 2


def cmd_signals(args) -> int:
    conn = connect()
    init_schema(conn)
    cfg = load_classifier_config()
    rows = list_demand_signals(
        conn,
        cfg.version,
        min_confidence=args.min_confidence,
        limit=args.limit,
    )
    if not rows:
        print(
            f"No demand signals found at version {cfg.version} "
            f"with confidence >= {args.min_confidence}."
        )
        return 0
    print(
        f"Top {len(rows)} demand signal(s) "
        f"(version {cfg.version}, min_confidence={args.min_confidence}):"
    )
    print()
    for r in rows:
        tags = json.loads(r["domain_tags"] or "[]")
        score = r["total_score"]
        print(f"[score {score}/25, conf {r['demand_confidence']:.2f}] {r['source_name']}")
        print(f"  {r['title']}")
        if r["summary"]:
            print(f"  -> {r['summary']}")
        print(
            f"  tags={','.join(tags)}  u={r['urgency_score']}  "
            f"buildable={r['solo_buildable_score']}  pain={r['workaround_pain']}  "
            f"pay={r['payment_evidence']}  niche={r['niche_specificity']}"
        )
        print(f"  {r['url']}")
        print()
    return 0


def cmd_dashboard(args) -> int:
    from ideascout.dashboard import generate_dashboard

    conn = connect()
    init_schema(conn)
    sync_sources_to_db(conn)
    result = generate_dashboard(conn, signal_limit=args.limit)
    print(f"Dashboard generated:")
    print(f"  posts (7d):    {result.posts_in_window}")
    print(f"  signals shown: {result.signals_in_window}")
    print(f"  written to:    {result.output_path}")
    if args.open:
        import webbrowser
        webbrowser.open(result.output_path.as_uri())
    return 0


def cmd_digest(args) -> int:
    from ideascout.digest import generate_digest

    conn = connect()
    init_schema(conn)
    sync_sources_to_db(conn)
    result = generate_digest(
        conn,
        top_n=args.top,
        table_limit=args.table_limit,
        write_file=not args.dry_run,
    )
    print(f"Digest {result.week_iso}:")
    print(f"  posts in window: {result.posts_count}")
    print(f"  demand signals:  {result.candidates_count}")
    if args.dry_run:
        print("  (dry run — no file written)")
        print()
        print(result.content_md)
    else:
        print(f"  written to:      {result.output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ideascout", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create DB and sync sources").set_defaults(func=cmd_init)
    sub.add_parser("sources", help="list configured sources").set_defaults(func=cmd_sources)

    p_poll = sub.add_parser("poll", help="poll every enabled source")
    p_poll.add_argument("--quiet", "-q", action="store_true")
    p_poll.set_defaults(func=cmd_poll)

    sub.add_parser("stats", help="post counts by source").set_defaults(func=cmd_stats)

    p_cls = sub.add_parser("classify", help="classify new posts via Ollama")
    p_cls.add_argument("--limit", type=int, default=None, help="cap posts per run")
    p_cls.add_argument("--quiet", "-q", action="store_true")
    p_cls.set_defaults(func=cmd_classify)

    p_sig = sub.add_parser("signals", help="show top demand signals")
    p_sig.add_argument("--limit", type=int, default=20)
    p_sig.add_argument("--min-confidence", type=float, default=0.5)
    p_sig.set_defaults(func=cmd_signals)

    p_dig = sub.add_parser("digest", help="generate weekly markdown digest")
    p_dig.add_argument("--top", type=int, default=5, help="top-N candidate detail blocks")
    p_dig.add_argument("--table-limit", type=int, default=20, help="rows in summary table")
    p_dig.add_argument("--dry-run", action="store_true", help="print to stdout, don't write file")
    p_dig.set_defaults(func=cmd_digest)

    p_dash = sub.add_parser("dashboard", help="generate self-contained HTML dashboard")
    p_dash.add_argument("--limit", type=int, default=50, help="signals to render")
    p_dash.add_argument("--open", action="store_true", help="open in default browser when done")
    p_dash.set_defaults(func=cmd_dashboard)

    return p


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(args.func(args))
