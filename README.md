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

## Tests

```bash
python3 tests/test_controller.py     # state machine + auto-advance, no mpv needed
```

Uses an in-process fake backend — no mpv, no network. Run the daemon itself with
`--fake` to exercise the socket API the same way.

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
