"""Integration test: real MpvBackend + Controller against a fake `mpv` binary
(tests/fake_mpv.py). Exercises spawn, IPC connect, warm start, loadfile, and
EOF auto-advance over an actual Unix socket. Not run in the nix build (which
stays hermetic); run manually: `python3 tests/test_mpv_integration.py`."""

import os
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def _install_fake_mpv(tmp: str) -> None:
    """Put an `mpv` shim on PATH that execs the fake, and point IPC/sockets at tmp."""
    shim = os.path.join(tmp, "mpv")
    with open(shim, "w") as f:
        f.write(f'#!/usr/bin/env bash\nexec {sys.executable} {HERE}/fake_mpv.py "$@"\n')
    os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    os.environ["PATH"] = tmp + os.pathsep + os.environ.get("PATH", "")
    os.environ["XDG_RUNTIME_DIR"] = tmp  # mpv IPC socket lands here


def _make_controller():
    from mediaplayer.backends import build_backends
    from mediaplayer.daemon import Controller

    return Controller(lambda on_eof: build_backends(on_eof, video=False))


def test_play_over_real_ipc():
    with tempfile.TemporaryDirectory() as tmp:
        _install_fake_mpv(tmp)
        c = _make_controller()
        try:
            c.enqueue("https://youtu.be/abc")
            r = c.play()
            assert r["state"] == "playing", r
            # backend actually spawned mpv and connected
            deadline = time.time() + 3
            while time.time() < deadline and not c.status()["backend"].get("running"):
                time.sleep(0.05)
            assert c.status()["backend"].get("running") is True, c.status()
        finally:
            c.shutdown()


def test_eof_auto_advance_over_real_ipc():
    os.environ["FAKE_MPV_EOF_MS"] = "150"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            _install_fake_mpv(tmp)
            c = _make_controller()
            try:
                c.enqueue("https://youtu.be/one")
                c.enqueue("https://youtu.be/two")
                c.play()
                # first item should EOF and advance to index 1 within ~1s
                deadline = time.time() + 3
                while time.time() < deadline and c.q.index != 1:
                    time.sleep(0.05)
                assert c.q.index == 1, f"expected advance, got index {c.q.index}"
                assert c.state == "playing"
            finally:
                c.shutdown()
    finally:
        os.environ.pop("FAKE_MPV_EOF_MS", None)


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
