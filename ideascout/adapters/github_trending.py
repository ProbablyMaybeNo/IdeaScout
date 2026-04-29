"""GitHub Trending adapter — HTML scrape of github.com/trending.

GitHub does not expose a /trending API endpoint. We parse the public HTML
which has been stable for years. We extract repo, description, language,
and the "X stars today" delta which is the signal that matters.

Config:
  language: optional spoken/programming language filter (e.g. "python")
  since: "daily" | "weekly" | "monthly"  (default daily)
  min_stars_today: minimum delta to keep a repo  (default 50)
"""
from __future__ import annotations

import hashlib
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


# Each repo is in an <article class="Box-row"> tag containing:
#   <h2 class="..."> <a href="/owner/repo">  ...  </a> </h2>
#   <p class="...">description</p>
#   <span itemprop="programmingLanguage">Python</span>
#   <span class="d-inline-block float-sm-right">N stars today</span>
ARTICLE_RE = re.compile(r'<article class="Box-row">(.+?)</article>', re.DOTALL)
# Repo link is inside <h2 class="h3 lh-condensed">. Other anchors in the
# article point to /stargazers, /sponsors, /pulls, etc. — anchor on the h2.
H2_HREF_RE = re.compile(
    r'<h2[^>]*class="[^"]*lh-condensed[^"]*"[^>]*>.*?<a[^>]+href="(/[^"]+/[^"]+?)"',
    re.DOTALL,
)
PARA_RE     = re.compile(r'<p[^>]*?class="col-9[^"]*"[^>]*>(.+?)</p>', re.DOTALL)
LANG_RE     = re.compile(r'<span itemprop="programmingLanguage">([^<]+)</span>')
STARS_TODAY = re.compile(r'(\d[\d,]*)\s+stars\s+(today|this\s+week|this\s+month)', re.IGNORECASE | re.DOTALL)
TAG_RE      = re.compile(r"<[^>]+>")
WHITESPACE  = re.compile(r"\s+")


def _strip_html(s: str) -> str:
    return WHITESPACE.sub(" ", TAG_RE.sub("", s)).strip()


@register_adapter("github_trending")
class GitHubTrendingAdapter:
    type_name: str

    def poll(self, config: dict) -> list[RawPost]:
        language = (config.get("language") or "").strip().lower()
        since = (config.get("since") or "daily").lower()
        if since not in {"daily", "weekly", "monthly"}:
            since = "daily"
        min_stars_today = int(config.get("min_stars_today", 50))

        path = "/trending"
        if language:
            path += f"/{urllib.parse.quote(language)}"
        url = f"https://github.com{path}?since={since}"

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html_doc = resp.read().decode("utf-8", errors="replace")

        posts: list[RawPost] = []
        for m in ARTICLE_RE.finditer(html_doc):
            block = m.group(1)

            href_m = H2_HREF_RE.search(block)
            if not href_m:
                continue
            slug = href_m.group(1).strip("/")
            if slug.count("/") != 1:
                continue

            title = slug  # e.g. "owner/repo"

            desc_m = PARA_RE.search(block)
            description = _strip_html(desc_m.group(1)) if desc_m else ""

            lang_m = LANG_RE.search(block)
            language_name = lang_m.group(1).strip() if lang_m else ""

            stars_m = STARS_TODAY.search(block)
            stars_today = 0
            stars_period = since
            if stars_m:
                stars_today = int(stars_m.group(1).replace(",", ""))
                stars_period = stars_m.group(2).lower()

            if stars_today < min_stars_today:
                continue

            external_id = hashlib.sha1(
                f"{slug}|{since}".encode()
            ).hexdigest()[:16]

            posts.append(
                RawPost(
                    external_id=external_id,
                    title=title,
                    url=f"https://github.com/{slug}",
                    body=description,
                    author=slug.split("/")[0],
                    posted_at=datetime.now(timezone.utc),
                    raw_payload={
                        "language": language_name,
                        "stars_in_period": stars_today,
                        "period": stars_period,
                    },
                )
            )

        return posts
