from ideascout.adapters.base import SourceAdapter, register_adapter, get_adapter
from ideascout.adapters import (  # noqa: F401  registers
    reddit,
    hackernews,
    rss,
    pulsemcp,
    github_trending,
    ycombinator,
)

__all__ = ["SourceAdapter", "register_adapter", "get_adapter"]
