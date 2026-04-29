"""Polls every enabled source and inserts new posts into the DB."""
from __future__ import annotations

import json
import sqlite3
import sys
import traceback
from dataclasses import dataclass

from ideascout.adapters import get_adapter
from ideascout.db import (
    insert_post_if_new,
    list_enabled_sources,
    mark_source_polled,
)


@dataclass(slots=True)
class PollResult:
    source_name: str
    source_type: str
    fetched: int
    inserted: int
    duplicates: int
    error: str | None = None


def poll_all(conn: sqlite3.Connection, *, verbose: bool = True) -> list[PollResult]:
    results: list[PollResult] = []
    for row in list_enabled_sources(conn):
        source_id = row["id"]
        name = row["name"]
        type_ = row["type"]
        config = json.loads(row["config_json"])

        try:
            adapter = get_adapter(type_)
        except KeyError as e:
            results.append(PollResult(name, type_, 0, 0, 0, error=str(e)))
            mark_source_polled(conn, source_id, error=str(e))
            if verbose:
                print(f"  [fail] {name}: {e}", file=sys.stderr)
            continue

        try:
            posts = adapter.poll(config)
        except Exception as e:  # noqa: BLE001 — adapter failures must not stop pipeline
            err = f"{type(e).__name__}: {e}"
            mark_source_polled(conn, source_id, error=err)
            results.append(PollResult(name, type_, 0, 0, 0, error=err))
            if verbose:
                print(f"  [fail] {name}: {err}", file=sys.stderr)
                traceback.print_exc(limit=2)
            continue

        inserted = 0
        duplicates = 0
        for post in posts:
            if insert_post_if_new(conn, source_id, post):
                inserted += 1
            else:
                duplicates += 1

        mark_source_polled(conn, source_id, error=None)
        results.append(
            PollResult(name, type_, len(posts), inserted, duplicates, error=None)
        )
        if verbose:
            print(
                f"  [ok]   {name}: fetched={len(posts)} new={inserted} dup={duplicates}"
            )

    return results
