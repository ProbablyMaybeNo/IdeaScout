from __future__ import annotations

from typing import Protocol

from ideascout.models import RawPost


class SourceAdapter(Protocol):
    """Every adapter implements `poll(config)` returning a list of RawPost."""

    type_name: str

    def poll(self, config: dict) -> list[RawPost]:
        ...


_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register_adapter(type_name: str):
    def deco(cls: type[SourceAdapter]) -> type[SourceAdapter]:
        cls.type_name = type_name
        _REGISTRY[type_name] = cls
        return cls

    return deco


def get_adapter(type_name: str) -> SourceAdapter:
    if type_name not in _REGISTRY:
        raise KeyError(
            f"Unknown adapter type {type_name!r}. Registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[type_name]()
