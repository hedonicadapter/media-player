"""In-process backend for tests — no mpv, no network. Records calls and can
simulate natural end-of-track via finish_current()."""

from __future__ import annotations

from typing import Callable

from ..queue import Item
from .base import Backend


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, on_eof: Callable[[], None]):
        self._on_eof = on_eof
        self.calls: list[tuple] = []
        self.loaded: str | None = None
        self.paused = False

    def load(self, item: Item) -> None:
        self.calls.append(("load", item.uri))
        self.loaded = item.uri
        self.paused = False

    def pause(self) -> None:
        self.calls.append(("pause",))
        self.paused = True

    def resume(self) -> None:
        self.calls.append(("resume",))
        self.paused = False

    def stop(self) -> None:
        self.calls.append(("stop",))
        self.loaded = None

    def status(self) -> dict:
        return {"engine": "fake", "loaded": self.loaded, "paused": self.paused}

    def finish_current(self) -> None:
        """Simulate the track playing to its end."""
        self.loaded = None
        self._on_eof()
