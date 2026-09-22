"""Small, UI-independent view models shared by desktop clients."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class FilterState:
    """The complete resource list query, independent of Qt widgets."""

    category: str | None = None
    view: str = "all"
    grade: str | list[str] = ""
    tags: list[str] = field(default_factory=list)
    types: set[str] = field(default_factory=set)
    query: str = ""
    sort: str = "name"


@dataclass(slots=True)
class ResourceView:
    """Stable display representation for a resource dictionary."""

    id: str
    path: str
    name: str
    type: str
    grade: str
    tags: list[str]
    category: str | None
    size: int
    mtime: float
    extension: str = ""

    @classmethod
    def from_dict(cls, resource: dict) -> "ResourceView":
        return cls(
            id=resource["id"],
            path=resource["path"],
            name=resource["name"],
            type=resource["type"],
            grade=resource.get("grade", ""),
            tags=list(resource.get("tags", [])),
            category=resource.get("category"),
            size=int(resource.get("size", 0)),
            mtime=float(resource.get("mtime", 0)),
            extension=resource.get("extension", ""),
        )
