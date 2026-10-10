# lgtv-follow

**Your Mac follows your LG TV's input.** Switch the TV to your PS5 and the Mac lets go of the
screen and sound; switch back and it takes them again. Automatically.

| When the TV switches to… | Your Mac… |
|---|---|
| **the Mac's HDMI input** | connects the TV as a display · plays audio through the TV |
| **anything else** (console, Apple TV, Netflix, standby) | disconnects the display, so your windows come back to the Mac · moves audio back to what you used before (AirPods, speakers…) |

It works however the input changes: the TV remote, a PS5 controller waking the console over
HDMI-CEC, or a hotkey on your Mac:

```sh
lgtv-follow toggle HDMI_4   # TV → Mac, or back to wherever you were
```

> **Why?** When an LG TV is your Mac's monitor and you switch it to another input, macOS keeps
> the TV as a display. Windows open on a screen you can't see and sound goes to an input you're not
> watching. lgtv-follow fixes both.

## Quick start

Needs macOS, an LG webOS TV on the same network (tested on a 2024 C4),
[BetterDisplay](https://betterdisplay.pro) (with its CLI integration enabled), Homebrew and
[uv](https://docs.astral.sh/uv/) (it fetches Python 3.11+ for you).

```sh
brew install uv betterdisplaycli switchaudio-osx
uv tool install git+https://github.com/kingsleydon/lgtv-follow

lgtv-follow init --host <TV IP> --display "<TV name in BetterDisplay>" --input HDMI_4
lgtv-follow pair      # accept the prompt on the TV (one time)
lgtv-follow install   # start now and at every login
```

That's it. Check `~/Library/Logs/lgtv-follow.log` to see it working, and give the TV a fixed IP
(a DHCP reservation on your router).

<details>
<summary>Finding the values</summary>

- **TV IP:** TV *Settings → Network*, or your router's device list
- **Display name:** `betterdisplaycli get --identifiers`
- **Which HDMI input the Mac is on:** `lgtv-follow inputs` (`*` marks the current input)
- **Audio output name:** `SwitchAudioSource -a -t output`
- **Sanity check:** `lgtv-follow check` (config, tools, pairing), and `lgtv-follow run --dry-run` to watch without changing anything
</details>

## Hotkeys for switching the TV

```sh
lgtv-follow switch HDMI_1    # go to an input (or any webOS app id)
lgtv-follow switch back      # go to the previous input
lgtv-follow toggle HDMI_4    # Mac ⇄ wherever you were before
```

The service remembers the previous input however it was changed, so `back` and `toggle` take
you back even if the console switched the TV. Bind them in any launcher, using the full path
from `which lgtv-follow`:

- **Shortcuts:** *Run Shell Script* action → *Add Keyboard Shortcut* (enable *Settings →
  Advanced → Allow Running Scripts*)
- **Raycast:** add [`contrib/script-commands`](contrib/script-commands) as a script directory
- **Tinycast, Alfred, BetterTouchTool…:** a shell-command action per hotkey

## Configuration

`~/.config/lgtv-follow/config.toml` (created by `init`):

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

A rule *enters* when the TV switches to one of its inputs, and *leaves* when the TV switches
away or goes to standby. At startup the current input is applied, so the Mac starts in sync.

- **`audio_on_leave = "previous"`** returns to the output in use before entering, falling back to
  the built-in speakers. If you picked another output yourself in the meantime, it's left alone.
- **Hooks** (`on_enter`, `on_leave`) are shell commands, run with `LGTV_RULE`, `LGTV_EVENT`
  (`enter`/`leave`) and `LGTV_INPUT` set. Rules can use hooks only, e.g. to change Focus
  mode when the console input comes up. See [examples/config.toml](examples/config.toml).

## Good to know

- **Away from home, or the TV is off:** nothing on the Mac changes. The service retries quietly
  every few seconds and picks up as soon as the TV is back. Hotkeys give up after a few seconds
  with a one-line error.
- **Mac not plugged into the TV:** the display and audio steps are skipped.
- **No surprise prompts:** only `lgtv-follow pair` asks the TV for permission. Everything else
  uses the stored key, or refuses to connect.
- **Instant, no polling:** the TV pushes input changes over its local webOS API and the Mac
  reacts right away. A `switch` hotkey takes about a quarter of a second.

### Compared with other tools

[BetterDisplay](https://github.com/waydabber/BetterDisplay) can switch the TV *to* the Mac on wake,
and [lg-tv-control-macos](https://github.com/cmer/lg-tv-control-macos) powers the TV on and off
with the Mac. Both control the TV from the Mac. lgtv-follow works the other way round, letting
the TV's input control the Mac. They work well together.

Why not HDMI-CEC? Macs can *send* CEC (BetterDisplay does), but there's no supported way to
*listen* to it. TVs also don't reliably announce switching to built-in apps or standby. The
webOS API reports every change.

## Update

```sh
uv tool upgrade lgtv-follow && lgtv-follow install
```

## Uninstall

```sh
lgtv-follow uninstall
uv tool uninstall lgtv-follow
rm -rf ~/.config/lgtv-follow ~/.local/state/lgtv-follow ~/Library/Logs/lgtv-follow.log
```

## Development

```sh
uv venv --python 3.13 && uv pip install -e '.[test]'
.venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Built on [bscpylgtv](https://github.com/chros73/bscpylgtv). MIT licensed.
