from ideascout.adapters.base import SourceAdapter, register_adapter, get_adapter
from ideascout.adapters import reddit, hackernews, indiehackers_rss  # noqa: F401  registers

__all__ = ["SourceAdapter", "register_adapter", "get_adapter"]
