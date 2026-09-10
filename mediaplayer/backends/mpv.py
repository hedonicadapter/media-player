"""mpv engine via JSON IPC. Covers YouTube, TikTok, local files, podcasts, and
DRM-free audiobooks — anything mpv (with yt-dlp) can resolve.

mpv is spawned once with --idle; the daemon reuses it for every item. A single
IPC socket carries both our commands and mpv's async events; one reader thread
watches for end-file so the daemon can auto-advance the queue."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from typing import Callable

from ..protocol import default_mpv_sock_path
from ..queue import Item
from .base import Backend


class MpvBackend(Backend):
    name = "mpv"

    def __init__(
        self,
        on_eof: Callable[[], None],
        video: bool = True,
        ipc_path: str | None = None,
        mpv_bin: str = "mpv",
    ):
        self._on_eof = on_eof
        self._video = video
        self._ipc_path = ipc_path or default_mpv_sock_path()
        self._mpv_bin = mpv_bin
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._current_uri: str = ""

    # --- lifecycle -------------------------------------------------------

    def warm(self) -> None:
        """Pre-spawn mpv in the background so the first play is instant. Non-fatal:
        if mpv is missing, load() surfaces the error later."""

        def _try():
            try:
                self._ensure_started()
            except Exception:
                pass

        threading.Thread(target=_try, daemon=True).start()

    def _ensure_started(self) -> None:
        with self._start_lock:
            self._ensure_started_locked()

    def _ensure_started_locked(self) -> None:
        if self._proc and self._proc.poll() is None and self._sock is not None:
            return
        if shutil.which(self._mpv_bin) is None:
            raise RuntimeError(
                f"'{self._mpv_bin}' not found on PATH. Install mpv (and yt-dlp for "
                "YouTube/TikTok) to play these sources."
            )
        try:
            os.unlink(self._ipc_path)
        except FileNotFoundError:
            pass

        args = [
            self._mpv_bin,
            "--idle=yes",
            "--no-terminal",
            "--force-window=no",
            f"--input-ipc-server={self._ipc_path}",
            "--keep-open=no",
        ]
        if not self._video:
            args.append("--no-video")
        self._proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._connect()
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()

    def _connect(self) -> None:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if os.path.exists(self._ipc_path):
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.connect(self._ipc_path)
                    self._sock = s
                    return
                except OSError:
                    pass
            time.sleep(0.05)
        raise RuntimeError("mpv IPC socket did not appear within 5s")

    # --- IPC -------------------------------------------------------------

    def _command(self, *args) -> None:
        if not self._sock:
            return
        payload = json.dumps({"command": list(args)}) + "\n"
        with self._send_lock:
            try:
                self._sock.sendall(payload.encode())
            except OSError:
                pass

    def _reader_loop(self) -> None:
        assert self._sock is not None
        buf = bytearray()
        f = self._sock
        while True:
            try:
                chunk = f.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf.extend(chunk)
            while b"\n" in buf:
                line, _, rest = bytes(buf).partition(b"\n")
                buf = bytearray(rest)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Natural completion -> advance queue. Ignore stop/skip (reason != eof).
                if msg.get("event") == "end-file" and msg.get("reason") == "eof":
                    try:
                        self._on_eof()
                    except Exception:
                        pass

    # --- Backend API -----------------------------------------------------

    def load(self, item: Item) -> None:
        self._ensure_started()
        self._current_uri = item.uri
        self._command("loadfile", item.uri, "replace")
        self._command("set_property", "pause", False)

    def pause(self) -> None:
        self._command("set_property", "pause", True)

    def resume(self) -> None:
        self._command("set_property", "pause", False)

    def stop(self) -> None:
        self._command("stop")
        self._current_uri = ""

    def status(self) -> dict:
        running = bool(self._proc and self._proc.poll() is None)
        return {"engine": "mpv", "running": running, "uri": self._current_uri}

    def shutdown(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._command("quit")
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._sock:
            self._sock.close()
