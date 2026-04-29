"""HackerNews adapter via the Algolia HN Search API. Free, no key.

Two query types:
  - front_page: stories with high score in the last 7 days
  - ask_hn: Ask HN posts in the last 30 days, optionally filtered by intent phrase
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from ideascout.adapters.base import register_adapter
from ideascout.models import RawPost

USER_AGENT = "IdeaScout/0.1 (https://github.com/ProbablyMaybeNo/IdeaScout)"
ALGOLIA_BASE = "https://hn.algolia.com/api/v1"


@register_adapter("hackernews")
class HackerNewsAdapter:
    type_name: str

    def poll(self, config: dict) -> list[RawPost]:
        query_type = config.get("query_type", "front_page")
        limit = int(config.get("limit", 30))
        intent_phrases = [p.lower() for p in config.get("intent_phrases", [])]

        if query_type == "front_page":
            since = int((datetime.now(tz=timezone.utc) - timedelta(days=7)).timestamp())
            params = {
                "tags": "story",
                "numericFilters": f"created_at_i>{since},points>50",
                "hitsPerPage": str(limit),
            }
            url = f"{ALGOLIA_BASE}/search_by_date?{urllib.parse.urlencode(params)}"
        elif query_type == "ask_hn":
            since = int((datetime.now(tz=timezone.utc) - timedelta(days=30)).timestamp())
            params = {
                "tags": "ask_hn",
                "numericFilters": f"created_at_i>{since}",
                "hitsPerPage": str(limit),
            }
            url = f"{ALGOLIA_BASE}/search_by_date?{urllib.parse.urlencode(params)}"
        else:
            raise ValueError(f"unknown HN query_type: {query_type!r}")

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        hits = payload.get("hits", [])
        posts: list[RawPost] = []
        for h in hits:
            external_id = str(h.get("objectID") or "")
            title = (h.get("title") or h.get("story_title") or "").strip()
            if not external_id or not title:
                continue
            body = (h.get("story_text") or h.get("comment_text") or "").strip()

            if intent_phrases:
                hay = (title + "\n" + body).lower()
                if not any(p in hay for p in intent_phrases):
                    continue

            url_full = (
                h.get("url")
                or f"https://news.ycombinator.com/item?id={external_id}"
            )
            created_iso = h.get("created_at")
            posted_at = None
            if created_iso:
                # Algolia returns ISO 8601 strings.
                try:
                    posted_at = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
                except ValueError:
                    posted_at = None

            posts.append(
                RawPost(
                    external_id=external_id,
                    title=title,
                    url=url_full,
                    body=body,
                    author=h.get("author"),
                    posted_at=posted_at,
                    raw_payload={
                        "points": h.get("points"),
                        "num_comments": h.get("num_comments"),
                        "tags": h.get("_tags"),
                    },
                )
            )

        return posts
