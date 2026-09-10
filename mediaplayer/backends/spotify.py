"""Spotify engine — PINNED / not implemented.

Spotify can't be driven like mpv: you can't legally pull raw audio. Playback must
run through a Spotify Connect device (the desktop app, or a headless librespot/
spotifyd), commanded via the Spotify Web API, and it requires a Premium account
plus an OAuth token. Planned design:

  1. OAuth (Authorization Code w/ PKCE), cache refresh token.
  2. Resolve a playlist URI -> track list via Web API.
  3. Pick an active Connect device (GET /me/player/devices).
  4. Control with PUT /me/player/play, /pause, POST /me/player/next.

Until then, enqueuing a Spotify URI raises so the daemon can report it clearly."""

from __future__ import annotations

from typing import Callable

from ..queue import Item
from .base import Backend


class SpotifyPinned(RuntimeError):
    pass


class SpotifyBackend(Backend):
    name = "spotify"

    def __init__(self, on_eof: Callable[[], None]):
        self._on_eof = on_eof

    def _pinned(self):
        raise SpotifyPinned(
            "Spotify backend is pinned (not implemented yet). Needs Web API OAuth + "
            "a Premium Connect device. Queue YouTube/TikTok/audiobook URIs for now."
        )

    def load(self, item: Item) -> None:
        self._pinned()

    def pause(self) -> None:
        self._pinned()

    def resume(self) -> None:
        self._pinned()

    def stop(self) -> None:
        # No-op: nothing to stop when never started.
        pass

    def status(self) -> dict:
        return {"engine": "spotify", "state": "pinned"}
