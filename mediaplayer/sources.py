"""Classify a URI into a source. Routing is coarse: everything mpv+yt-dlp can resolve
(YouTube, TikTok, local files, podcasts, DRM-free audiobooks) shares one backend;
Spotify is its own path."""

from __future__ import annotations

import os
from urllib.parse import urlparse

YOUTUBE = "youtube"
TIKTOK = "tiktok"
SPOTIFY = "spotify"
AUDIOBOOK = "audiobook"
GENERIC = "generic"

# Source -> backend name. mpv covers everything except Spotify.
BACKEND_FOR = {
    YOUTUBE: "mpv",
    TIKTOK: "mpv",
    AUDIOBOOK: "mpv",
    GENERIC: "mpv",
    SPOTIFY: "spotify",
}

_AUDIO_EXTS = {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg", ".opus", ".wav"}


def classify(uri: str) -> str:
    u = uri.strip()
    low = u.lower()

    if low.startswith("spotify:") or "open.spotify.com" in low:
        return SPOTIFY
    if "youtube.com" in low or "youtu.be" in low:
        return YOUTUBE
    if "tiktok.com" in low:
        return TIKTOK

    # Local file or file:// -> audio extension reads as audiobook.
    has_scheme = "://" in u
    path = urlparse(u).path if has_scheme else u
    ext = os.path.splitext(path)[1].lower()
    is_local = low.startswith("file://") or not has_scheme
    if is_local and ext in _AUDIO_EXTS:
        return AUDIOBOOK

    return GENERIC


def backend_name(source: str) -> str:
    return BACKEND_FOR.get(source, "mpv")
