"""Playback backends. One instance per engine, shared across queue items."""

from __future__ import annotations

from typing import Callable

from .base import Backend


def build_backends(on_eof: Callable[[], None], video: bool = True) -> dict[str, Backend]:
    """Construct the backend registry. Import lazily so a missing engine only
    fails when its source is actually played."""
    from .mpv import MpvBackend
    from .spotify import SpotifyBackend

    return {
        "mpv": MpvBackend(on_eof=on_eof, video=video),
        "spotify": SpotifyBackend(on_eof=on_eof),
    }
