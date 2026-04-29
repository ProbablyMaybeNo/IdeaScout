from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class RawPost:
    """Normalised post returned by every adapter, before persistence."""

    external_id: str
    title: str
    url: str
    body: str = ""
    author: str | None = None
    posted_at: datetime | None = None
    raw_payload: dict = field(default_factory=dict)


@dataclass(slots=True)
class StoredPost:
    """Post as it lives in the DB — adds source_id and surrogate id."""

    id: int
    source_id: int
    external_id: str
    title: str
    url: str
    body: str
    author: str | None
    posted_at: datetime | None
    scraped_at: datetime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
