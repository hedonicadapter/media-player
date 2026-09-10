"""Queue + item model. Pure data; no playback here."""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field

from . import sources

_ids = itertools.count(1)


@dataclass
class Item:
    uri: str
    source: str = ""
    title: str = ""
    id: int = field(default_factory=lambda: next(_ids))

    def __post_init__(self):
        if not self.source:
            self.source = sources.classify(self.uri)
        if not self.title:
            self.title = self.uri

    def to_dict(self) -> dict:
        return asdict(self)


class Queue:
    """Ordered items with a cursor. Cursor -1 means nothing selected."""

    def __init__(self):
        self.items: list[Item] = []
        self.index: int = -1

    def enqueue(self, uri: str) -> Item:
        item = Item(uri=uri)
        self.items.append(item)
        if self.index == -1:
            self.index = 0
        return item

    def current(self) -> Item | None:
        if 0 <= self.index < len(self.items):
            return self.items[self.index]
        return None

    def advance(self) -> Item | None:
        """Move cursor to next item. None when past the end."""
        if self.index + 1 < len(self.items):
            self.index += 1
            return self.items[self.index]
        self.index = len(self.items)  # park past end
        return None

    def clear(self) -> None:
        self.items.clear()
        self.index = -1

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "items": [i.to_dict() for i in self.items],
        }
