"""HTTP control-surface test — fake backend, ephemeral port, no mpv/network out."""

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mediaplayer.backends.fake import FakeBackend  # noqa: E402
from mediaplayer.daemon import Controller  # noqa: E402
from mediaplayer.http_api import start_http  # noqa: E402


def _controller():
    return Controller(lambda on_eof: {"mpv": FakeBackend(on_eof), "spotify": FakeBackend(on_eof)})


def _req(port, path, token=None, method="POST"):
    url = f"http://127.0.0.1:{port}{path}"
    r = urllib.request.Request(url, method=method)
    if token:
        r.add_header("X-Token", token)
    with urllib.request.urlopen(r, timeout=3) as resp:
        return resp.status, json.loads(resp.read())


def test_routes_drive_controller():
    httpd = start_http(_controller(), "127.0.0.1", 0, None)
    port = httpd.server_address[1]
    try:
        _, r = _req(port, "/enqueue?uri=https://youtu.be/a")
        assert r["item"]["source"] == "youtube"
        _, r = _req(port, "/play")
        assert r["state"] == "playing"
        _, r = _req(port, "/status", method="GET")
        assert r["state"] == "playing"
        _, r = _req(port, "/pause")
        assert r["state"] == "paused"
        _, r = _req(port, "/next")
        assert r["ok"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_enqueue_requires_uri():
    httpd = start_http(_controller(), "127.0.0.1", 0, None)
    port = httpd.server_address[1]
    try:
        try:
            _req(port, "/enqueue")
            assert False, "expected 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_token_enforced():
    httpd = start_http(_controller(), "127.0.0.1", 0, "s3cret")
    port = httpd.server_address[1]
    try:
        try:
            _req(port, "/play")  # no token
            assert False, "expected 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401
        _, r = _req(port, "/play", token="s3cret")
        assert r["ok"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
