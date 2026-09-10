"""Backend interface. Each engine (mpv, spotify, ...) implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..queue import Item


class Backend(ABC):
    """A playback engine. The daemon owns the queue and drives one item at a time.

    Implementations report end-of-track by calling the `on_eof` callback given
    at construction, so the daemon can auto-advance. `on_eof` must fire only on
    natural completion, never on an explicit stop/skip (which the daemon drives)."""

    name: str = "base"

    @abstractmethod
    def load(self, item: Item) -> None:
        """Start playing item from the beginning."""

    @abstractmethod
    def pause(self) -> None:
        ...

    @abstractmethod
    def resume(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop and unload. Must not trigger on_eof."""

    def status(self) -> dict:
        return {}

    def shutdown(self) -> None:
        """Release engine resources on daemon exit."""
