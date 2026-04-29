"""PulseMCP adapter via the public v0beta JSON API.

Returns recently-published MCP servers ordered by listing recency. Each
server is mapped to a RawPost where:
  - title  = server name
  - body   = AI-generated description + short_description
  - url    = pulsemcp.com listing URL (for browser viewing)
  - raw    = github_stars, download_count, source_code_url, package info

This is one of the highest-signal sources for a solo dev publishing MCP
servers — gaps in the listing landscape ARE product opportunities.
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ideascout.adapters.base import register_adapter
from ideascout.models import RawPost

USER_AGENT = "IdeaScout/0.1 (https://github.com/ProbablyMaybeNo/IdeaScout)"
API_BASE = "https://api.pulsemcp.com/v0beta"


@register_adapter("pulsemcp")
class PulseMcpAdapter:
    type_name: str

    def poll(self, config: dict) -> list[RawPost]:
        limit = int(config.get("limit", 50))
        # The API max is 5000 per request and supports a query param.
        query = (config.get("query") or "").strip()

        params = {"count_per_page": str(min(limit, 100))}
        if query:
            params["query"] = query

        url = f"{API_BASE}/servers?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        servers = payload.get("servers") or []
        posts: list[RawPost] = []
        for s in servers[:limit]:
            name = (s.get("name") or "").strip()
            if not name:
                continue
            listing_url = s.get("url") or s.get("external_url") or ""
            if not listing_url:
                continue

            # PulseMCP doesn't return a stable id; hash the listing URL.
            external_id = hashlib.sha1(listing_url.encode()).hexdigest()[:16]

            short = (s.get("short_description") or "").strip()
            ai_desc = (s.get("EXPERIMENTAL_ai_generated_description") or "").strip()
            body = "\n\n".join(b for b in (short, ai_desc) if b)

            stars = s.get("github_stars")
            downloads = s.get("package_download_count")

            posts.append(
                RawPost(
                    external_id=external_id,
                    title=name,
                    url=listing_url,
                    body=body,
                    author=None,
                    posted_at=datetime.now(timezone.utc),
                    raw_payload={
                        "github_stars": stars,
                        "package_download_count": downloads,
                        "source_code_url": s.get("source_code_url"),
                        "package_registry": s.get("package_registry"),
                        "package_name": s.get("package_name"),
                        "external_url": s.get("external_url"),
                    },
                )
            )

        return posts
