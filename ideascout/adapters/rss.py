"""Generic RSS / Atom adapter. Works for any feed_url."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser

from ideascout.adapters.base import register_adapter
from ideascout.models import RawPost


@register_adapter("rss")
class RssAdapter:
    type_name: str

    def poll(self, config: dict) -> list[RawPost]:
        feed_url = config["feed_url"]
        limit = int(config.get("limit", 30))
        intent_phrases = [p.lower() for p in config.get("intent_phrases", [])]

        parsed = feedparser.parse(feed_url)
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(
                f"feedparser failed on {feed_url}: {parsed.bozo_exception!r}"
            )

        posts: list[RawPost] = []
        for entry in parsed.entries[:limit]:
            external_id = (
                entry.get("id")
                or entry.get("guid")
                or entry.get("link")
                or ""
            )
            title = (entry.get("title") or "").strip()
            if not external_id or not title:
                continue
            body = (
                entry.get("summary")
                or entry.get("description")
                or ""
            ).strip()

            if intent_phrases:
                hay = (title + "\n" + body).lower()
                if not any(p in hay for p in intent_phrases):
                    continue

            url_full = entry.get("link") or ""
            posted_at = _parse_entry_date(entry)
            author = entry.get("author") or None

            posts.append(
                RawPost(
                    external_id=external_id,
                    title=title,
                    url=url_full,
                    body=body,
                    author=author,
                    posted_at=posted_at,
                    raw_payload={
                        "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")],
                    },
                )
            )

        return posts


def _parse_entry_date(entry) -> datetime | None:
    for key in ("published", "updated", "created"):
        s = entry.get(key)
        if not s:
            continue
        try:
            dt = parsedate_to_datetime(s)
        except (TypeError, ValueError):
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None
