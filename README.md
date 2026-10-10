# lgtv-follow

Make your Mac follow an LG webOS TV's input.

Using an LG TV as a Mac monitor *and* for a console or streaming? Switch the TV however you
like — remote, a PS5 controller waking the console over HDMI-CEC, a hotkey — and the Mac keeps up:

```
TV → HDMI 4 (the Mac)    display connected, audio → TV
TV → anything else       display disconnected, audio → whatever you used before (or the speakers)
```

No invisible desktop swallowing your windows, no sound going to an input you're not watching.

It listens to the TV's webOS network API for input changes (push events, no polling), and drives
[BetterDisplay](https://betterdisplay.pro) and
[SwitchAudioSource](https://github.com/deweller/switchaudio-osx). It can also switch the TV's
input from the Mac, so a hotkey can take you to the Mac and back.

### How it relates to other tools

[BetterDisplay](https://github.com/waydabber/BetterDisplay) can switch the TV *to* the Mac on wake,
and [lg-tv-control-macos](https://github.com/cmer/lg-tv-control-macos) powers the TV with the Mac.
Both drive the TV from the Mac. lgtv-follow goes the other way: the TV's input drives the Mac.
They work fine together.

Why not HDMI-CEC? Macs can send CEC (BetterDisplay does), but there's no supported way to listen
to it, and TVs don't reliably announce switching to built-in apps or standby. The webOS API
reports every change.

## Requirements

- macOS, Python 3.9+
- An LG webOS TV on the same network (tested on a 2024 C4)
- [BetterDisplay](https://betterdisplay.pro) with CLI integration enabled and
  `brew install betterdisplaycli` — for `display`
- `brew install switchaudio-osx` — for `audio_output`

## Install

```sh
uv tool install git+https://github.com/kingsleydon/lgtv-follow   # or: pipx install git+…

lgtv-follow init --host 192.168.1.50 --display "LG TV SSCR2"
lgtv-follow pair       # accept the prompt on the TV
lgtv-follow inputs     # list inputs; * marks the current one
lgtv-follow check      # validate config and tools
lgtv-follow install    # run at login (launchd)
```

Give the TV a fixed IP (a DHCP reservation on your router). `lgtv-follow run --dry-run` shows
what would happen without changing anything. Logs: `~/Library/Logs/lgtv-follow.log`.

## Configuration

`~/.config/lgtv-follow/config.toml`:

```toml
[tv]
host = "192.168.1.50"

[[rule]]
name = "mac"
input = "HDMI_4"               # HDMI_n or any webOS app id; a list is fine
display = "LG TV SSCR2"        # BetterDisplay: connect on enter, disconnect on leave
audio_output = "LG TV SSCR2"   # select this output on enter
audio_on_leave = "previous"    # "previous" (default), "builtin", "none" or a device name
on_enter = []                  # extra shell commands
on_leave = []
```

A rule *enters* when the TV switches to one of its inputs and *leaves* when it switches away or
goes to standby. On startup the current input is applied, so the Mac starts in sync.

- **Audio on leave:** `previous` returns to the output in use before the rule entered (e.g.
  AirPods), falling back to the built-in speakers. If you changed the output yourself in the
  meantime, it's left alone.
- **Hooks:** `on_enter` / `on_leave` commands get `LGTV_RULE`, `LGTV_EVENT` (`enter`/`leave`)
  and `LGTV_INPUT` in their environment.
- **Names:** `betterdisplaycli get --identifiers` lists displays,
  `SwitchAudioSource -a -t output` lists audio outputs.

More in [examples/config.toml](examples/config.toml).

### Away from the TV

When the TV is off, on another network, or you're simply not home, nothing on the Mac is
touched: the service retries quietly every few seconds (logging only when reachability
changes) and picks up as soon as the TV is back. `switch`/`toggle` give up after a few seconds
with a one-line message and exit code 1. If the TV isn't plugged into this Mac, display and
audio steps are skipped.

Only `lgtv-follow pair` ever asks the TV for permission. Everything else uses the stored key and
refuses to connect without one, so no pairing prompt pops up on the TV unexpectedly.

## Switching inputs from the Mac

```sh
lgtv-follow switch HDMI_1    # an input or app
lgtv-follow switch back      # the previous input
lgtv-follow toggle HDMI_4    # on HDMI 4 -> previous input; anywhere else -> HDMI 4
```

The service remembers the previous input however it was changed, so `back` and `toggle` return
to where you were even if a console switched the TV.

Bind these to hotkeys with any launcher, using the full path from `which lgtv-follow`:

- **Shortcuts:** a *Run Shell Script* action, then *Add Keyboard Shortcut* in its details
  (enable *Settings → Advanced → Allow Running Scripts*).
- **Raycast:** add [`contrib/script-commands`](contrib/script-commands) as a script directory.
- **Tinycast and others:** add a custom shell command per input.

## Uninstall

```sh
lgtv-follow uninstall
uv tool uninstall lgtv-follow
rm -rf ~/.config/lgtv-follow ~/.local/state/lgtv-follow
```

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Built on [bscpylgtv](https://github.com/chros73/bscpylgtv). MIT licensed.
