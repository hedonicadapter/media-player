"""mediactl — thin client for the daemon. Hooks and humans both drive playback
through this. Commands that need a running daemon auto-spawn one."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback

from .protocol import default_sock_path, request

# Commands that should boot the daemon if it isn't up yet.
_AUTOSTART = {"play", "enqueue", "toggle", "ensure-daemon"}


def _daemon_up(sock_path: str) -> bool:
    try:
        resp = request(sock_path, {"cmd": "ping"}, timeout=1.0)
        return bool(resp.get("ok"))
    except (OSError, ValueError):
        return False


def _log_path(sock_path: str) -> str:
    return os.path.join(os.path.dirname(sock_path) or ".", "mediaplayer-daemon.log")


def _log_tail(sock_path: str, n: int = 20) -> str:
    try:
        with open(_log_path(sock_path), "r", errors="replace") as f:
            return "".join(f.readlines()[-n:]).rstrip()
    except OSError:
        return "(no daemon log)"


def _daemon_argv(sock_path: str, video: bool) -> list[str]:
    argv = ["--socket", sock_path]
    if not video:
        argv.append("--no-video")
    return argv


def _fork_daemon(sock_path: str, video: bool) -> None:
    """Double-fork and run the daemon in-process. The running client already has
    `mediaplayer` imported, so the child inherits it — no interpreter re-invoke,
    no PATH/PYTHONPATH dependency (which broke under nix's `nix run`)."""
    pid = os.fork()
    if pid > 0:
        try:
            os.waitpid(pid, 0)  # reap intermediate child (exits right after 2nd fork)
        except ChildProcessError:
            pass
        return  # parent: caller polls for the socket
    try:
        os.setsid()
        if os.fork() > 0:
            os._exit(0)  # first child exits; grandchild reparents to init
        # Grandchild = daemon. Detach stdio to the log file.
        log_fd = os.open(_log_path(sock_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        null_fd = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null_fd, 0)
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        from .daemon import main as daemon_main

        daemon_main(_daemon_argv(sock_path, video))
    except BaseException:
        traceback.print_exc()
        os._exit(1)
    os._exit(0)


def _subprocess_daemon(sock_path: str, video: bool) -> None:
    """Fallback for platforms without fork: re-invoke the interpreter, forcing the
    package onto PYTHONPATH so a bare interpreter can import it."""
    log = open(_log_path(sock_path), "ab")
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = pkg_parent + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [sys.executable, "-m", "mediaplayer.daemon", *_daemon_argv(sock_path, video)]
    subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True, close_fds=True, env=env)


def ensure_daemon(sock_path: str, video: bool = True) -> bool:
    if _daemon_up(sock_path):
        return True
    if hasattr(os, "fork"):
        _fork_daemon(sock_path, video)
    else:
        _subprocess_daemon(sock_path, video)
    deadline = time.time() + 8.0
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
            print(f"error: could not start daemon ({_log_path(sock)})", file=sys.stderr)
            print("--- daemon log tail ---", file=sys.stderr)
            print(_log_tail(sock), file=sys.stderr)
            return 1
        if args.command == "ensure-daemon":
            return _emit({"ok": True, "started": True}, args.json)

    req: dict = {"cmd": args.command}
    if args.command == "enqueue":
        req["uri"] = args.uri

    try:
        # Generous timeout: a cold first play may still spin up mpv inside the
        # handler before the warm start finishes.
        resp = request(sock, req, timeout=20.0)
    except (OSError, ValueError) as e:
        # A non-autostart command against a dead daemon: report cleanly.
        print(f"error: daemon not reachable ({e})", file=sys.stderr)
        return 1
    return _emit(resp, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
