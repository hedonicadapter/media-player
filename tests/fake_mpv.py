#!/usr/bin/env python3
"""Minimal mpv IPC emulator for tests — no audio/video, just the socket protocol
MpvBackend speaks. Understands --input-ipc-server=PATH and --idle; accepts a
client, reads newline-JSON commands, replies with success, and (if
FAKE_MPV_EOF_MS is set) emits an end-file/eof event after a loadfile so
auto-advance can be exercised over real IPC."""

import json
import os
import socket
import sys
import threading
import time


def ipc_path_from_argv(argv):
    for a in argv:
        if a.startswith("--input-ipc-server="):
            return a.split("=", 1)[1]
    return None


def main():
    path = ipc_path_from_argv(sys.argv[1:])
    if not path:
        sys.stderr.write("fake_mpv: no --input-ipc-server\n")
        return 2
    eof_ms = int(os.environ.get("FAKE_MPV_EOF_MS", "0"))

    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(4)

    stop = threading.Event()

    def handle(conn):
        buf = bytearray()
        with conn:
            while not stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
                while b"\n" in buf:
                    line, _, rest = bytes(buf).partition(b"\n")
                    buf = bytearray(rest)
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cmd = msg.get("command", [])
                    conn.sendall(b'{"error":"success"}\n')
                    if cmd and cmd[0] == "quit":
                        stop.set()
                        return
                    if cmd and cmd[0] == "loadfile" and eof_ms > 0:
                        def _eof(c=conn):
                            time.sleep(eof_ms / 1000.0)
                            try:
                                c.sendall(b'{"event":"end-file","reason":"eof"}\n')
                            except OSError:
                                pass
                        threading.Thread(target=_eof, daemon=True).start()

    srv.settimeout(0.3)
    while not stop.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=handle, args=(conn,), daemon=True).start()

    srv.close()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
