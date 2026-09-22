"""Application controller used by the Qt presentation layer.

Keeping query and command orchestration here makes the UI replaceable while
preserving the Library service as the only owner of filesystem mutations.
"""

from __future__ import annotations

from .models import FilterState


class LibraryController:
    def __init__(self, library):
        self.library = library

    def query(self, filters: FilterState) -> list[dict]:
        grade_values = filters.grade if isinstance(filters.grade, (list, tuple, set)) else None
        rows = self.library.resources(
            category=filters.category,
            view=filters.view,
            grade="" if grade_values is not None else filters.grade,
            tags=filters.tags,
            query=filters.query,
        )
        if grade_values:
            rows = [row for row in rows if row.get("grade", "") in grade_values]
        if filters.types:
            rows = [row for row in rows if row["type"] in filters.types]
        if filters.sort == "size":
            rows.sort(key=lambda row: row["size"], reverse=True)
        elif filters.sort == "grade":
            rows.sort(key=lambda row: (row.get("grade") or "Z", row["name"].casefold()))
        return rows

    def scan(self):
        return self.library.scan()

    def categories(self):
        return self.library.categories()

    def tags(self):
        return self.library.tags()
