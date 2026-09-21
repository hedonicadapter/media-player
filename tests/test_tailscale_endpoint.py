"""Tailscale endpoint discovery without a live Tailscale daemon."""

from __future__ import annotations

import json
import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mediaplayer import cli  # noqa: E402


class Result:
    stdout = json.dumps({"Self": {"DNSName": "speaker.tailnet.ts.net."}})


def test_tailscale_endpoint_uses_magicdns_name():
    with patch("mediaplayer.cli.subprocess.run", return_value=Result()) as run:
        assert cli.tailscale_endpoint(9123) == "http://speaker.tailnet.ts.net:9123"
    assert run.call_args.args[0] == ["tailscale", "status", "--json"]


def test_tailscale_endpoint_cli_output():
    output = StringIO()
    with patch("mediaplayer.cli.tailscale_endpoint", return_value="http://speaker.tailnet.ts.net:8730"):
        with redirect_stdout(output):
            assert cli.main(["tailscale-endpoint"]) == 0
    assert output.getvalue() == "OPENCODE_MEDIA_PLAYER_ENDPOINTS=http://speaker.tailnet.ts.net:8730\n"


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
