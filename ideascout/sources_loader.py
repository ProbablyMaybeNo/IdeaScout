"""Loads sources.yaml and syncs definitions to the DB."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from ideascout.db import upsert_source

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"


def load_sources_yaml(path: Path = DEFAULT_CONFIG_PATH) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a list of source definitions")
    return data


def sync_sources_to_db(
    conn: sqlite3.Connection, path: Path = DEFAULT_CONFIG_PATH
) -> int:
    """Upsert each source into the DB. Returns number processed."""
    sources = load_sources_yaml(path)
    for src in sources:
        upsert_source(
            conn,
            name=src["name"],
            type_=src["type"],
            config=src.get("config", {}),
            enabled=bool(src.get("enabled", True)),
        )
    return len(sources)
