"""Optional localhost HTTP control surface. Off unless enabled (a port only opens
when asked). Maps GET/POST /play,/pause,/toggle,/next,/stop,/clear,/status and
/enqueue?uri=... onto the same Controller the socket API uses.

Bind host defaults to 127.0.0.1. Binding to anything else exposes playback control
to other hosts — set a token then, and know the token still crosses the network
in the clear."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_ROUTES = {
    "": "status",
    "status": "status",
    "play": "play",
    "pause": "pause",
    "toggle": "toggle",
    "next": "next",
    "stop": "stop",
    "clear": "clear",
    "enqueue": "enqueue",
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # --- helpers ---------------------------------------------------------

    def _token_ok(self, query: dict) -> bool:
        token = self.server.token  # type: ignore[attr-defined]
        if not token:
            return True
        got = self.headers.get("X-Token") or (query.get("token", [None])[0])
        return got == token

    def _send(self, code: int, obj: dict) -> None:
        body = (json.dumps(obj) + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self):
        parsed = urlparse(self.path)
        route = parsed.path.strip("/").lower()
        query = parse_qs(parsed.query)
        if not self._token_ok(query):
            self._send(401, {"ok": False, "error": "bad token"})
            return
        cmd = _ROUTES.get(route)
        if cmd is None:
            self._send(404, {"ok": False, "error": f"no route /{route}"})
            return
        c = self.server.controller  # type: ignore[attr-defined]
        if cmd == "enqueue":
            uri = (query.get("uri", [""])[0]).strip()
            if not uri:
                self._send(400, {"ok": False, "error": "enqueue needs ?uri="})
                return
            self._send(200, c.enqueue(uri))
            return
        self._send(200, getattr(c, cmd)())

    # --- verbs -----------------------------------------------------------

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        # Drain any body so the connection can be reused, then dispatch.
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._dispatch()

    def log_message(self, *_):  # silence default stderr logging
        pass


def start_http(controller, host: str, port: int, token: str | None) -> ThreadingHTTPServer:
    """Bind and serve in a daemon thread. Raises OSError on bind failure."""
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.controller = controller  # type: ignore[attr-defined]
    httpd.token = token  # type: ignore[attr-defined]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
