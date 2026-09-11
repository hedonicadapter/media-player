# media-player

An agnostic media player daemon you queue things onto — YouTube videos, TikToks,
audiobooks, podcasts, local files — and drive from **Claude Code hooks**: it
autoplays while you wait on the LLM and pauses when the turn finishes.

Spotify is designed for but **pinned** (not implemented — see below).

## How it works

```
Claude Code hooks ──▶ mediactl ──▶ daemon ──▶ backend ──▶ player
   (play / pause)      (CLI)      (queue +    (per source)
                                   state)
```

- **daemon** — long-lived; owns the queue and a small state machine
  (`idle → playing ⇄ paused`), routes each item to a backend, auto-advances at
  end of track. Listens on a Unix socket.
- **mediactl** — thin client. Hooks and you both drive playback through it.
- **backends** — pluggable engines behind one interface:
  - `mpv` (via [mpv](https://mpv.io) + [yt-dlp](https://github.com/yt-dlp/yt-dlp))
    covers **YouTube, TikTok, audiobooks, podcasts, local files** — anything
    yt-dlp resolves. One mpv process, controlled over its JSON IPC socket.
  - `spotify` — **pinned**, raises a clear error if played (see Roadmap).

Source is chosen by URI (`mediaplayer/sources.py`); everything but Spotify shares
the mpv engine.

## Requirements

- Python ≥ 3.9 (stdlib only — no pip deps)
- `mpv` and `yt-dlp` on `PATH` for real playback:
  ```
  # macOS:  brew install mpv yt-dlp
  # Debian: sudo apt install mpv && pipx install yt-dlp
  ```

The daemon runs without them; it only errors when you actually play a source
whose engine is missing.

## Run with Nix

The flake bundles Python + mpv + yt-dlp, so nothing else is needed:

```bash
nix run github:hedonicadapter/media-player -- enqueue "https://youtu.be/dQw4w9WgXcQ"
nix run github:hedonicadapter/media-player -- play
nix run github:hedonicadapter/media-player -- status
nix run github:hedonicadapter/media-player#daemon -- --no-video   # run the daemon directly
```

`nix run` (no `#`) is `mediactl`; `#daemon` is the daemon. Install to your profile
with `nix profile install github:hedonicadapter/media-player` to get `mediactl` on
PATH, or drop into a dev shell with `nix develop`.

For hooks, point the sample config at the installed binary (e.g.
`~/.nix-profile/bin/mediactl`) instead of `bin/mediactl`.

## Use

```bash
# optional: install console scripts (mediactl, mediaplayer-daemon)
pip install -e .
# or run uninstalled via the shim:  ./bin/mediactl <cmd>

mediactl enqueue "https://youtu.be/dQw4w9WgXcQ"
mediactl enqueue "https://www.tiktok.com/@user/video/123"
mediactl enqueue "~/audiobooks/book.m4b"
mediactl play        # start / resume
mediactl pause       # hold; resumes same item on next play
mediactl next        # skip
mediactl status      # state + queue (--json for machine output)
mediactl stop        # stop, keep queue
mediactl clear       # stop + empty queue
```

Commands that need it (`play`, `enqueue`, `toggle`, `ensure-daemon`) auto-start
the daemon. Audio-only: pass `--no-video` (applied when the daemon autostarts),
or start the daemon yourself: `mediaplayer-daemon --no-video`.

Socket path: `$MEDIAPLAYER_SOCK`, else `$XDG_RUNTIME_DIR/mediaplayer.sock`.

## Claude Code hook wiring

The feature: play while waiting on the LLM, pause when the turn ends.

| Hook | Command | Why |
|---|---|---|
| `SessionStart` | `mediactl ensure-daemon` | boot the daemon idempotently |
| `UserPromptSubmit` | `mediactl play` | you submitted → now waiting |
| `Stop` | `mediactl pause` | turn finished (spans tool calls; `Stop` fires only at turn end) |
| `Notification` | `mediactl pause` | pause if it stalls waiting on input |

`pause` (not `stop`) so playback resumes mid-item next turn instead of
restarting. See [`hooks/settings.sample.json`](hooks/settings.sample.json) —
copy the `hooks` block into `~/.claude/settings.json` (global) or a project
`.claude/settings.json`, and replace `/ABS/PATH` with this checkout. Commands are
silenced and `|| true`'d so they never block or delay a turn.

## External trigger (HTTP)

For a trigger that speaks HTTP instead of running a command, the daemon can open
a **localhost** control endpoint. It's off by default — a port only opens when
you enable it:

```bash
# enable when starting the daemon directly …
mediaplayer-daemon --http                 # port 8730
# … or via env, so an autostarted (hook/forked) daemon inherits it:
export MEDIAPLAYER_HTTP_PORT=8730
```

Then your external signal just hits a URL — GET or POST, JSON back:

```bash
curl -X POST localhost:8730/play          # waiting on the LLM → play
curl -X POST localhost:8730/pause         # finished → pause
curl -X POST 'localhost:8730/enqueue?uri=https://youtu.be/…'
curl localhost:8730/status
```

Routes: `/play /pause /toggle /next /stop /clear /status /enqueue?uri=…`.

Since an HTTP trigger can't autostart the daemon, make sure it's already up with
HTTP on — e.g. a `SessionStart` hook running `mediactl ensure-daemon` with
`MEDIAPLAYER_HTTP_PORT` exported, or run `mediaplayer-daemon --http` yourself.

**Security:** binds `127.0.0.1` only, no auth by default (any local process can
drive it). To reach it from another host, set `--http-host 0.0.0.0` **and** a
token (`--http-token …` or `MEDIAPLAYER_HTTP_TOKEN`), sent as an `X-Token` header
or `?token=`. The token still crosses the network in the clear — prefer an SSH
tunnel over exposing the port.

## Tests

```bash
python3 tests/test_controller.py       # state machine + auto-advance
python3 tests/test_autostart.py        # in-process fork autostart
python3 tests/test_http_api.py         # HTTP control surface
python3 tests/test_mpv_integration.py  # real MpvBackend vs a fake mpv IPC binary
```

All use an in-process fake backend — no mpv, no outbound network. Run the daemon
itself with `--fake` to exercise the socket API the same way.

## Roadmap / Spotify

Spotify can't be driven like mpv — you can't legally pull raw audio. Playback has
to run through a Spotify **Connect** device (the desktop app, or headless
`librespot`/`spotifyd`), commanded via the Web API, and it needs a **Premium**
account + OAuth. Planned `SpotifyBackend`:

1. OAuth (Authorization Code + PKCE), cache the refresh token.
2. Resolve playlist URI → track list (Web API).
3. Pick an active Connect device.
4. Control via `PUT /me/player/play`, `/pause`, `POST /me/player/next`.

Other likely additions: live title/position in `status`, per-item audio/video
override, shuffle, a debounce so back-to-back turns don't stutter.
