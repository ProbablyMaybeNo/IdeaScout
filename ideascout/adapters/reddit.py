"""Reddit adapter using the public /r/{sub}/new.json endpoint.

No auth needed for low-volume polling. Reddit allows ~60 requests/min unauthenticated;
we poll well below that.
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

from ideascout.adapters.base import register_adapter
from ideascout.models import RawPost

USER_AGENT = "IdeaScout/0.1 (https://github.com/ProbablyMaybeNo/IdeaScout)"


@register_adapter("reddit")
class RedditAdapter:
    type_name: str

    def poll(self, config: dict) -> list[RawPost]:
        subreddit = config["subreddit"]
        limit = int(config.get("limit", 50))
        intent_phrases = [p.lower() for p in config.get("intent_phrases", [])]

        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        # Reddit rate-limits aggressively; one retry with backoff on 429.
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt == 0:
                    time.sleep(5)
                    continue
                raise

        children = payload.get("data", {}).get("children", [])
        posts: list[RawPost] = []
        for child in children:
            d = child.get("data", {})
            external_id = d.get("id")
            title = (d.get("title") or "").strip()
            if not external_id or not title:
                continue
            body = (d.get("selftext") or "").strip()

            if intent_phrases:
                hay = (title + "\n" + body).lower()
                if not any(p in hay for p in intent_phrases):
                    continue

            permalink = d.get("permalink", "")
            url_full = (
                f"https://www.reddit.com{permalink}"
                if permalink.startswith("/")
                else d.get("url") or ""
            )
            created = d.get("created_utc")
            posted_at = (
                datetime.fromtimestamp(created, tz=timezone.utc) if created else None
            )

            posts.append(
                RawPost(
                    external_id=external_id,
                    title=title,
                    url=url_full,
                    body=body,
                    author=d.get("author"),
                    posted_at=posted_at,
                    raw_payload={
                        "score": d.get("score"),
                        "num_comments": d.get("num_comments"),
                        "subreddit": subreddit,
                    },
                )
            )

        return posts
