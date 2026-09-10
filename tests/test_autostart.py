"""Regression test: `ensure_daemon` forks a reachable daemon in-process, without
re-invoking an interpreter (the path that broke under nix's `nix run`, where a
bare interpreter can't import the package). No mpv needed."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mediaplayer import cli  # noqa: E402
from mediaplayer.protocol import request  # noqa: E402


def test_autostart_brings_up_reachable_daemon():
    if not hasattr(os, "fork"):
        print("SKIP (no fork on this platform)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_RUNTIME_DIR"] = tmp
        sock = os.path.join(tmp, "mp.sock")
        try:
            assert cli.ensure_daemon(sock, video=False) is True, "daemon did not come up"
            assert request(sock, {"cmd": "ping"}).get("ok") is True
            r = request(sock, {"cmd": "enqueue", "uri": "https://youtu.be/x"})
            assert r["item"]["source"] == "youtube"
            assert request(sock, {"cmd": "status"})["queue"]["items"], "queue empty"
        finally:
            try:
                request(sock, {"cmd": "shutdown"})
            except OSError:
                pass


if __name__ == "__main__":
    import traceback

    try:
        test_autostart_brings_up_reachable_daemon()
        print("PASS test_autostart_brings_up_reachable_daemon")
    except Exception:
        traceback.print_exc()
        print("FAIL test_autostart_brings_up_reachable_daemon")
        raise SystemExit(1)
