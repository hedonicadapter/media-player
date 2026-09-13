"""Auto routing: internal mpv when the queue has items, system player when empty."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mediaplayer.backends.fake import FakeBackend  # noqa: E402
from mediaplayer.daemon import Controller  # noqa: E402


class FakeSystem:
    def __init__(self):
        self.calls = []

    def _do(self, a):
        self.calls.append(a)
        return {"ok": True, "action": a, "tool": "fake"}

    def play(self):
        return self._do("play")

    def pause(self):
        return self._do("pause")

    def toggle(self):
        return self._do("toggle")

    def next(self):
        return self._do("next")

    def describe(self):
        return {"available": True, "driver": "fake", "tool": "fake"}


def _make():
    holder = {}

    def factory(on_eof):
        fb = FakeBackend(on_eof)
        holder["fb"] = fb
        return {"mpv": fb, "spotify": fb}

    sysc = FakeSystem()
    c = Controller(factory, system=sysc)
    return c, holder["fb"], sysc


def test_empty_queue_forwards_to_system():
    c, fb, sysc = _make()
    r = c.play()
    assert r["mode"] == "system"
    assert sysc.calls == ["play"]
    assert fb.loaded is None  # mpv untouched
    c.pause()
    c.next()
    assert sysc.calls == ["play", "pause", "next"]


def test_queued_items_use_internal_not_system():
    c, fb, sysc = _make()
    c.enqueue("https://youtu.be/a")
    r = c.play()
    assert r["mode"] == "internal"
    assert fb.loaded == "https://youtu.be/a"
    assert sysc.calls == []  # system never touched
    c.pause()
    assert fb.paused is True
    assert sysc.calls == []


def test_pause_follows_mode_after_system_play():
    c, fb, sysc = _make()
    c.play()          # empty -> system
    c.pause()         # must go to system, not no-op internal
    assert sysc.calls == ["play", "pause"]


def test_exhausted_queue_next_goes_system():
    c, fb, sysc = _make()
    c.enqueue("a.mp3")
    c.play()
    c.next()          # advance past end -> queue exhausted
    # now current() is None; a further next should forward to system
    c.next()
    assert sysc.calls == ["next"]


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
