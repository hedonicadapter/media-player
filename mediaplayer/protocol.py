"""Newline-delimited JSON over a Unix socket. One request, one response per connection."""

from __future__ import annotations

import json
import os
import socket
import tempfile


def default_sock_path() -> str:
    runtime = os.environ.get("MEDIAPLAYER_SOCK")
    if runtime:
        return runtime
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(base, "mediaplayer.sock")


def default_mpv_sock_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(base, "mediaplayer-mpv.sock")


def send_json(sock: socket.socket, obj: dict) -> None:
    sock.sendall((json.dumps(obj) + "\n").encode())


def recv_json(sock: socket.socket) -> dict | None:
    """Read one newline-terminated JSON object. None on clean EOF."""
    buf = bytearray()
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            if not buf:
                return None
            break
        buf.extend(chunk)
    line, _, _ = bytes(buf).partition(b"\n")
    if not line.strip():
        return None
    return json.loads(line)


def request(sock_path: str, obj: dict, timeout: float = 5.0) -> dict:
    """Connect, send one request, return the one response."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(sock_path)
        send_json(s, obj)
        resp = recv_json(s)
        return resp if resp is not None else {"ok": False, "error": "no response"}
