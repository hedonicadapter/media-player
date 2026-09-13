"""System-wide media control — pause/resume whatever holds the OS media session,
regardless of app. This is the agnostic path for Spotify and anything else you
didn't queue internally: migrate Spotify -> Tidal -> Apple Music -> a media
server and this keeps working.

Drivers, picked at runtime:
  - Linux:  playerctl (MPRIS over D-Bus). Targets the most-recently-active
            player; scope to one with MEDIAPLAYER_PLAYERCTL_PLAYER=spotify.
  - macOS:  nowplaying-cli if installed (true system Now Playing), else
            AppleScript against a running player app (Spotify/Music by default,
            override with MEDIAPLAYER_MAC_PLAYER).

Global by nature: on macOS (and Linux without a scoped player) it hits whatever
the OS calls active, so if mpv and Spotify both play they fight — scope the
player, or rely on Auto routing (system control only kicks in when the internal
queue is empty)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# action -> per-driver subcommand
_PLAYERCTL = {"play": "play", "pause": "pause", "toggle": "play-pause", "next": "next", "previous": "previous"}
_NOWPLAYING = {"play": "play", "pause": "pause", "toggle": "togglePlayPause", "next": "next", "previous": "previous"}
_APPLE_VERB = {"play": "play", "pause": "pause", "toggle": "playpause", "next": "next track", "previous": "previous track"}


class SystemController:
    def __init__(self, which=shutil.which, runner=None, platform: str | None = None):
        self._which = which
        self._run = runner or _default_run
        self._platform = platform or sys.platform
        self.driver, self.tool = self._detect()

    def _detect(self) -> tuple[str | None, str | None]:
        if self._platform.startswith("linux"):
            return ("playerctl", "playerctl") if self._which("playerctl") else (None, None)
        if self._platform == "darwin":
            if self._which("nowplaying-cli"):
                return "nowplaying", "nowplaying-cli"
            if self._which("osascript"):
                return "applescript", "osascript"
        return (None, None)

    @property
    def available(self) -> bool:
        return self.driver is not None

    # --- command construction (pure; unit-tested) ------------------------

    def _mac_apps(self) -> list[str]:
        env = os.environ.get("MEDIAPLAYER_MAC_PLAYER")
        return [env] if env else ["Spotify", "Music"]

    def _applescript(self, verb: str) -> str:
        # First running app in the list wins.
        parts = []
        for i, app in enumerate(self._mac_apps()):
            head = "if" if i == 0 else "else if"
            parts.append(f'{head} application "{app}" is running then tell application "{app}" to {verb}')
        parts.append("end if")
        return "\n".join(parts)

    def argv(self, action: str) -> list[str] | None:
        if self.driver == "playerctl":
            player = os.environ.get("MEDIAPLAYER_PLAYERCTL_PLAYER")
            scope = ["-p", player] if player else []
            return ["playerctl", *scope, _PLAYERCTL[action]]
        if self.driver == "nowplaying":
            return ["nowplaying-cli", _NOWPLAYING[action]]
        if self.driver == "applescript":
            return ["osascript", "-e", self._applescript(_APPLE_VERB[action])]
        return None

    # --- actions ---------------------------------------------------------

    def _do(self, action: str) -> dict:
        argv = self.argv(action)
        if argv is None:
            return {"ok": False, "action": action, "error": "no system media control on this platform"}
        code, err = self._run(argv)
        out = {"ok": code == 0, "action": action, "tool": self.tool}
        if code != 0:
            out["error"] = err or f"exit {code}"
        return out

    def play(self) -> dict:
        return self._do("play")

    def pause(self) -> dict:
        return self._do("pause")

    def toggle(self) -> dict:
        return self._do("toggle")

    def next(self) -> dict:
        return self._do("next")

    def previous(self) -> dict:
        return self._do("previous")

    def describe(self) -> dict:
        return {"available": self.available, "driver": self.driver, "tool": self.tool}


def _default_run(argv: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, timeout=5)
        return p.returncode, p.stderr.decode(errors="replace").strip()
    except FileNotFoundError:
        return 127, f"{argv[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
