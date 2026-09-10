"""mediactl — thin client for the daemon. Hooks and humans both drive playback
through this. Commands that need a running daemon auto-spawn one."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from .protocol import default_sock_path, request

# Commands that should boot the daemon if it isn't up yet.
_AUTOSTART = {"play", "enqueue", "toggle", "ensure-daemon"}


def _daemon_up(sock_path: str) -> bool:
    try:
        resp = request(sock_path, {"cmd": "ping"}, timeout=1.0)
        return bool(resp.get("ok"))
    except (OSError, ValueError):
        return False


def ensure_daemon(sock_path: str, video: bool = True) -> bool:
    if _daemon_up(sock_path):
        return True
    log_dir = os.path.dirname(sock_path) or "."
    log = open(os.path.join(log_dir, "mediaplayer-daemon.log"), "ab")
    # Prefer the installed console script (correctly wrapped under nix/pip);
    # fall back to the module for uninstalled/dev use.
    daemon_bin = shutil.which("mediaplayer-daemon")
    if daemon_bin:
        cmd = [daemon_bin, "--socket", sock_path]
    else:
        cmd = [sys.executable, "-m", "mediaplayer.daemon", "--socket", sock_path]
    if not video:
        cmd.append("--no-video")
    subprocess.Popen(
        cmd, stdout=log, stderr=log, start_new_session=True,
        close_fds=True, cwd=os.getcwd(),
    )
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if _daemon_up(sock_path):
            return True
        time.sleep(0.1)
    return False


def _emit(resp: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(resp))
        return 0 if resp.get("ok") else 1
    if not resp.get("ok"):
        print(f"error: {resp.get('error', 'unknown')}", file=sys.stderr)
        return 1
    _print_human(resp)
    return 0


def _print_human(resp: dict) -> None:
    if resp.get("pong"):
        print(f"daemon ok (v{resp.get('version')})")
        return
    if "item" in resp:
        it = resp["item"]
        print(f"queued #{it['id']} [{it['source']}] {it['uri']}")
        return
    if "state" in resp:
        state = resp["state"]
        cur = resp.get("current")
        line = f"[{state}]"
        if cur:
            line += f" #{cur['id']} [{cur['source']}] {cur['title']}"
        print(line)
        q = resp.get("queue", {})
        items, idx = q.get("items", []), q.get("index", -1)
        for i, it in enumerate(items):
            mark = "▶" if i == idx else " "
            print(f"  {mark} #{it['id']} [{it['source']}] {it['title']}")
        return
    print(json.dumps(resp))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mediactl", description="control the media player daemon")
    p.add_argument("--socket", default=default_sock_path())
    p.add_argument("--json", action="store_true", help="raw JSON output")
    p.add_argument("--no-video", action="store_true", help="audio only (applies when autostarting)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("play", help="start or resume")
    sub.add_parser("pause", help="pause (resumes same item next play)")
    sub.add_parser("toggle", help="toggle play/pause")
    sub.add_parser("next", help="skip to next queue item")
    sub.add_parser("stop", help="stop, keep queue")
    sub.add_parser("clear", help="stop and empty the queue")
    sub.add_parser("status", help="show state + queue")
    e = sub.add_parser("enqueue", help="add a URI to the queue")
    e.add_argument("uri")
    sub.add_parser("ping", help="health check")
    sub.add_parser("ensure-daemon", help="start daemon if not running")
    sub.add_parser("shutdown", help="stop the daemon")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sock = args.socket
    video = not args.no_video

    if args.command in _AUTOSTART:
        if not ensure_daemon(sock, video=video):
            print("error: could not start daemon (see mediaplayer-daemon.log)", file=sys.stderr)
            return 1
        if args.command == "ensure-daemon":
            return _emit({"ok": True, "started": True}, args.json)

    req: dict = {"cmd": args.command}
    if args.command == "enqueue":
        req["uri"] = args.uri

    try:
        resp = request(sock, req)
    except (OSError, ValueError) as e:
        # A non-autostart command against a dead daemon: report cleanly.
        print(f"error: daemon not reachable ({e})", file=sys.stderr)
        return 1
    return _emit(resp, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
