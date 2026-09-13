"""Daemon: owns the queue + playback state machine, routes items to backends,
serves a Unix-socket control API. Auto-advances on natural end-of-track.

State machine: idle -> playing <-> paused. `play` starts/resumes, `pause` holds
(resumes same item next turn), `stop` unloads but keeps the queue."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading
from typing import Callable

from . import __version__, sources
from .backends import build_backends
from .backends.base import Backend
from .protocol import default_sock_path, recv_json, send_json
from .queue import Queue
from .system_control import SystemController

IDLE, PLAYING, PAUSED = "idle", "playing", "paused"
INTERNAL, SYSTEM = "internal", "system"


class Controller:
    """Queue + state machine. Thread-safe: control thread and backend eof thread
    both mutate through `lock`.

    Auto routing: with items queued, playback drives the internal mpv engine
    (queue, auto-advance). With the queue empty, play/pause/next forward to the
    OS media session (SystemController) so you can pause/resume Spotify or
    whatever else is playing."""

    def __init__(self, backend_factory, system: SystemController | None = None):
        self.q = Queue()
        self.state = IDLE
        self.mode = INTERNAL  # which target the last play/next acted on
        self.lock = threading.RLock()
        self.backends = backend_factory(self._on_eof)
        self._active: Backend | None = None
        self._last_system: dict = {}
        self.system = system if system is not None else SystemController()

    def warm_all(self) -> None:
        """Pre-start engines so the first play has no cold-start latency. Called
        after the control socket is listening so nothing here can delay bind."""
        for b in set(self.backends.values()):
            try:
                b.warm()
            except Exception:
                pass

    def _route(self, source: str) -> Backend:
        return self.backends[sources.backend_name(source)]

    def _load(self, item) -> None:
        self._active = self._route(item.source)
        self._active.load(item)
        self.state = PLAYING

    # --- commands --------------------------------------------------------

    def enqueue(self, uri: str) -> dict:
        with self.lock:
            item = self.q.enqueue(uri)
            return {"ok": True, "item": item.to_dict()}

    def play(self) -> dict:
        with self.lock:
            cur = self.q.current()
            if cur is None:  # nothing queued -> forward to the OS media session
                self.mode = SYSTEM
                self._last_system = self.system.play()
                return self.status()
            self.mode = INTERNAL
            if self.state == PLAYING:
                return self.status()
            if self.state == PAUSED and self._active is not None:
                self._active.resume()
                self.state = PLAYING
            else:  # idle -> load current from the top
                self._load(cur)
            return self.status()

    def pause(self) -> dict:
        with self.lock:
            if self.mode == SYSTEM:
                self._last_system = self.system.pause()
                return self.status()
            if self.state == PLAYING and self._active is not None:
                self._active.pause()
                self.state = PAUSED
            return self.status()

    def toggle(self) -> dict:
        with self.lock:
            if self.mode == SYSTEM and self.q.current() is None:
                self._last_system = self.system.toggle()
                return self.status()
            return self.pause() if self.state == PLAYING else self.play()

    def next(self) -> dict:
        with self.lock:
            if self.q.current() is None:  # queue empty/exhausted -> skip system track
                self.mode = SYSTEM
                self._last_system = self.system.next()
                return self.status()
            self.mode = INTERNAL
            nxt = self.q.advance()
            if nxt is not None:
                self._load(nxt)
            else:
                self._stop_active()
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            if self.mode == SYSTEM:
                self._last_system = self.system.pause()  # no universal "stop"; pause is closest
                return self.status()
            self._stop_active()
            return self.status()

    def _stop_active(self) -> None:
        if self._active is not None:
            self._active.stop()
        self.state = IDLE

    def clear(self) -> dict:
        with self.lock:
            self._stop_active()
            self.q.clear()
            return self.status()

    def _on_eof(self) -> None:
        """Backend reported natural end-of-track (from its own thread)."""
        with self.lock:
            nxt = self.q.advance()
            if nxt is not None:
                self._load(nxt)
            else:
                self.state = IDLE  # track already ended; nothing to stop

    def status(self) -> dict:
        with self.lock:
            cur = self.q.current()
            return {
                "ok": True,
                "state": self.state,
                "mode": self.mode,
                "current": cur.to_dict() if cur else None,
                "queue": self.q.to_dict(),
                "backend": self._active.status() if self._active else {},
                "system": {**self.system.describe(), "last": self._last_system},
            }

    def shutdown(self) -> None:
        with self.lock:
            for b in set(self.backends.values()):
                try:
                    b.shutdown()
                except Exception:
                    pass


class Server:
    def __init__(self, sock_path: str, controller: Controller, http: dict | None = None):
        self.sock_path = sock_path
        self.controller = controller
        self.http = http  # {"host","port","token"} or None
        self.running = False
        self._listen: socket.socket | None = None
        self._httpd = None

    def _dispatch(self, req: dict) -> dict:
        cmd = req.get("cmd")
        c = self.controller
        if cmd == "ping":
            return {"ok": True, "pong": True, "version": __version__}
        if cmd == "enqueue":
            uri = req.get("uri", "").strip()
            if not uri:
                return {"ok": False, "error": "enqueue requires 'uri'"}
            return c.enqueue(uri)
        if cmd in ("status", "list"):
            return c.status()
        if cmd == "play":
            return c.play()
        if cmd == "pause":
            return c.pause()
        if cmd == "toggle":
            return c.toggle()
        if cmd == "next":
            return c.next()
        if cmd == "stop":
            return c.stop()
        if cmd == "clear":
            return c.clear()
        if cmd == "shutdown":
            self.running = False
            return {"ok": True, "shutdown": True}
        return {"ok": False, "error": f"unknown command: {cmd!r}"}

    def serve(self) -> None:
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
        self._listen = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listen.bind(self.sock_path)
        os.chmod(self.sock_path, 0o600)
        self._listen.listen(8)
        self._listen.settimeout(0.5)
        self.running = True
        self.controller.warm_all()  # socket is live; warm engines in background
        self._start_http()

        while self.running:
            try:
                conn, _ = self._listen.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    req = recv_json(conn)
                    if req is None:
                        continue
                    resp = self._dispatch(req)
                except Exception as e:  # never let one bad client kill the daemon
                    resp = {"ok": False, "error": str(e)}
                try:
                    send_json(conn, resp)
                except OSError:
                    pass

        self._cleanup()

    def _start_http(self) -> None:
        if not self.http:
            return
        from .http_api import start_http

        try:
            self._httpd = start_http(self.controller, **self.http)
            print(
                f"http control on {self.http['host']}:{self.http['port']}"
                + ("" if self.http.get("token") else " (no token)"),
                file=sys.stderr,
            )
        except OSError as e:
            print(f"http control failed to bind: {e}", file=sys.stderr)

    def _cleanup(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        self.controller.shutdown()
        if self._listen:
            self._listen.close()
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass


def _fake_factory(on_eof):
    from .backends.fake import FakeBackend

    fb = FakeBackend(on_eof)
    return {"mpv": fb, "spotify": fb}


def _http_config(args) -> dict | None:
    """Resolve HTTP control config from flags, falling back to env. Enabled when
    --http/--http-port is given or MEDIAPLAYER_HTTP_PORT is set, so an autostarted
    (forked) daemon inherits it from the environment."""
    env = os.environ
    port = args.http_port or (int(env["MEDIAPLAYER_HTTP_PORT"]) if env.get("MEDIAPLAYER_HTTP_PORT") else 0)
    if not args.http and not port:
        return None
    return {
        "host": args.http_host or env.get("MEDIAPLAYER_HTTP_HOST", "127.0.0.1"),
        "port": port or 8730,
        "token": args.http_token or env.get("MEDIAPLAYER_HTTP_TOKEN") or None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mediaplayer-daemon")
    p.add_argument("--socket", default=default_sock_path())
    p.add_argument("--no-video", action="store_true", help="audio only (mpv --no-video)")
    p.add_argument("--fake", action="store_true", help="use in-process fake backend")
    p.add_argument("--http", action="store_true", help="enable localhost HTTP control on port 8730")
    p.add_argument("--http-host", default="", help="HTTP bind host (default 127.0.0.1)")
    p.add_argument("--http-port", type=int, default=0, help="HTTP port (implies --http)")
    p.add_argument("--http-token", default="", help="require this token (X-Token header or ?token=)")
    args = p.parse_args(argv)

    video = not args.no_video
    if args.fake:
        factory = _fake_factory
    else:
        factory = lambda on_eof: build_backends(on_eof, video=video)  # noqa: E731

    controller = Controller(factory)
    server = Server(args.socket, controller, http=_http_config(args))

    def _sig(*_):
        server.running = False

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    print(f"mediaplayer daemon {__version__} on {args.socket}", file=sys.stderr)
    d = controller.system.describe()
    print(
        f"system media control: {d['tool']}" if d["available"] else "system media control: unavailable",
        file=sys.stderr,
    )
    server.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
