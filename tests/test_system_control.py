"""SystemController: driver detection + argv construction, with injected
which/platform/runner. No real playerctl/osascript needed."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mediaplayer.system_control import SystemController  # noqa: E402


def _which(present):
    return lambda name: f"/usr/bin/{name}" if name in present else None


def _recorder():
    calls = []

    def run(argv):
        calls.append(argv)
        return 0, ""

    return calls, run


def test_linux_playerctl():
    os.environ.pop("MEDIAPLAYER_PLAYERCTL_PLAYER", None)
    sc = SystemController(which=_which({"playerctl"}), platform="linux")
    assert sc.available and sc.driver == "playerctl"
    assert sc.argv("play") == ["playerctl", "play"]
    assert sc.argv("toggle") == ["playerctl", "play-pause"]
    assert sc.argv("next") == ["playerctl", "next"]


def test_linux_playerctl_scoped():
    os.environ["MEDIAPLAYER_PLAYERCTL_PLAYER"] = "spotify"
    try:
        sc = SystemController(which=_which({"playerctl"}), platform="linux")
        assert sc.argv("pause") == ["playerctl", "-p", "spotify", "pause"]
    finally:
        os.environ.pop("MEDIAPLAYER_PLAYERCTL_PLAYER", None)


def test_linux_without_playerctl_unavailable():
    sc = SystemController(which=_which(set()), platform="linux")
    assert not sc.available
    r = sc.play()
    assert r["ok"] is False


def test_macos_nowplaying_preferred():
    sc = SystemController(which=_which({"nowplaying-cli", "osascript"}), platform="darwin")
    assert sc.driver == "nowplaying"
    assert sc.argv("toggle") == ["nowplaying-cli", "togglePlayPause"]


def test_macos_applescript_fallback():
    os.environ.pop("MEDIAPLAYER_MAC_PLAYER", None)
    sc = SystemController(which=_which({"osascript"}), platform="darwin")
    assert sc.driver == "applescript"
    argv = sc.argv("toggle")
    assert argv[:2] == ["osascript", "-e"]
    assert "playpause" in argv[2] and "Spotify" in argv[2] and "Music" in argv[2]


def test_do_invokes_runner():
    calls, run = _recorder()
    sc = SystemController(which=_which({"playerctl"}), platform="linux", runner=run)
    r = sc.pause()
    assert r["ok"] is True and r["action"] == "pause"
    assert calls == [["playerctl", "pause"]]


def test_unsupported_platform():
    sc = SystemController(which=_which({"playerctl"}), platform="win32")
    assert not sc.available
    assert sc.argv("play") is None


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
