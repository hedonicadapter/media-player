"""State-machine + queue tests using the fake backend. No mpv, no network."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mediaplayer.backends.fake import FakeBackend  # noqa: E402
from mediaplayer.daemon import IDLE, PAUSED, PLAYING, Controller  # noqa: E402


def make_controller():
    holder = {}

    def factory(on_eof):
        fb = FakeBackend(on_eof)
        holder["fake"] = fb
        return {"mpv": fb, "spotify": fb}

    c = Controller(factory)
    return c, holder["fake"]


def test_enqueue_then_play_loads_first():
    c, fb = make_controller()
    c.enqueue("https://youtu.be/a")
    assert c.state == IDLE  # enqueue never auto-plays
    c.play()
    assert c.state == PLAYING
    assert fb.loaded == "https://youtu.be/a"


def test_pause_resumes_same_item():
    c, fb = make_controller()
    c.enqueue("https://youtu.be/a")
    c.play()
    c.pause()
    assert c.state == PAUSED
    assert fb.paused is True
    c.play()  # resume, not reload
    assert c.state == PLAYING
    assert ("resume",) in fb.calls
    assert fb.calls.count(("load", "https://youtu.be/a")) == 1


def test_eof_auto_advances():
    c, fb = make_controller()
    c.enqueue("https://youtu.be/a")
    c.enqueue("https://tiktok.com/@x/video/1")
    c.play()
    fb.finish_current()  # natural end of item 1
    assert c.state == PLAYING
    assert fb.loaded == "https://tiktok.com/@x/video/1"
    assert c.q.index == 1


def test_eof_at_end_goes_idle():
    c, fb = make_controller()
    c.enqueue("https://youtu.be/only")
    c.play()
    fb.finish_current()
    assert c.state == IDLE


def test_next_skips():
    c, fb = make_controller()
    c.enqueue("a.mp3")
    c.enqueue("b.mp3")
    c.play()
    c.next()
    assert c.q.index == 1
    assert fb.loaded == "b.mp3"


def test_stop_keeps_queue_then_replays_from_top():
    c, fb = make_controller()
    c.enqueue("https://youtu.be/a")
    c.play()
    c.stop()
    assert c.state == IDLE
    assert len(c.q.items) == 1
    c.play()  # idle -> reload current
    assert fb.loaded == "https://youtu.be/a"


def test_play_empty_queue_noop():
    c, fb = make_controller()
    r = c.play()
    assert r["state"] == IDLE
    assert fb.loaded is None


def test_status_shape():
    c, _ = make_controller()
    c.enqueue("https://youtu.be/a")
    s = c.status()
    assert s["ok"] and s["state"] == IDLE
    assert s["current"]["source"] == "youtube"
    assert s["queue"]["index"] == 0


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
