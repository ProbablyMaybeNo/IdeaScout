"""Y Combinator companies adapter.

Returns recent batch companies from ycombinator.com/companies. The list
page renders companies into a Next.js shell whose JSON payload sits in
__NEXT_DATA__. We pull that and parse it directly — more stable than
parsing the HTML cards.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ideascout.adapters.base import register_adapter
from ideascout.models import RawPost

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
    re.DOTALL,
)


@register_adapter("ycombinator")
class YCombinatorAdapter:
    type_name: str

    def poll(self, config: dict) -> list[RawPost]:
        batch = (config.get("batch") or "").strip()
        limit = int(config.get("limit", 50))

        params: dict[str, str] = {}
        if batch:
            params["batch"] = batch
        url = "https://www.ycombinator.com/companies"
        if params:
            url += f"?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html_doc = resp.read().decode("utf-8", errors="replace")

        m = NEXT_DATA_RE.search(html_doc)
        if not m:
            raise RuntimeError("YC companies page: __NEXT_DATA__ not found")
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"YC __NEXT_DATA__ JSON parse failure: {e}") from e

        # The list lives somewhere under props.pageProps. The structure has
        # shifted historically, so walk lookng for the first list of dicts
        # that contain "name" and "slug" keys.
        companies = _find_companies(data) or []
        if not companies:
            raise RuntimeError("YC __NEXT_DATA__ did not contain a recognisable companies list")

        posts: list[RawPost] = []
        for c in companies[:limit]:
            slug = c.get("slug") or c.get("id")
            name = (c.get("name") or "").strip()
            if not slug or not name:
                continue
            tagline = (c.get("one_liner") or c.get("description") or c.get("long_description") or "").strip()
            tags = c.get("tags") or c.get("industry_groups") or []
            tag_str = ", ".join(t for t in tags if isinstance(t, str)) if isinstance(tags, list) else ""

            external_id = hashlib.sha1(str(slug).encode()).hexdigest()[:16]
            url_full = f"https://www.ycombinator.com/companies/{slug}"

            body_parts = []
            if tagline:
                body_parts.append(tagline)
            if tag_str:
                body_parts.append(f"Tags: {tag_str}")
            if c.get("batch"):
                body_parts.append(f"Batch: {c['batch']}")
            if c.get("status"):
                body_parts.append(f"Status: {c['status']}")

            posts.append(
                RawPost(
                    external_id=external_id,
                    title=name,
                    url=url_full,
                    body="\n".join(body_parts),
                    author=None,
                    posted_at=datetime.now(timezone.utc),
                    raw_payload={
                        "batch": c.get("batch"),
                        "industry": c.get("industry"),
                        "team_size": c.get("team_size"),
                        "website": c.get("website"),
                    },
                )
            )

        return posts


def _find_companies(data) -> list | None:
    """DFS for the first list of dicts that look like YC companies."""
    if isinstance(data, list):
        if data and isinstance(data[0], dict) and "name" in data[0] and (
            "slug" in data[0] or "id" in data[0]
        ):
            return data
        for item in data:
            r = _find_companies(item)
            if r:
                return r
    elif isinstance(data, dict):
        for v in data.values():
            r = _find_companies(v)
            if r:
                return r
    return None
