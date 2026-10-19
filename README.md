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

## Install

You need macOS, an LG webOS TV on the same network (tested on a 2024 C4), and
[BetterDisplay](https://betterdisplay.pro).

### With your AI agent (recommended)

Paste this into Claude Code, Codex, Cursor or any agent that can run commands on your Mac:

```text
Install lgtv-follow on my Mac by following
https://raw.githubusercontent.com/kingsleydon/lgtv-follow/main/docs/agent-install.md
```

The agent installs the tools, finds your TV and its display name, and sets up the background
service. You only need to accept the pairing prompt on the TV. It can set up hotkeys too.
([What it follows](docs/agent-install.md).)

### Manual setup

Requires [Homebrew](https://brew.sh). In BetterDisplay's Settings, enable command-line
integration.

```sh
# 1. Tools: uv (Python installer), BetterDisplay's CLI, audio switcher
brew install uv betterdisplaycli switchaudio-osx

# 2. lgtv-follow itself (uv fetches Python 3.11+ if needed)
uv tool install git+https://github.com/kingsleydon/lgtv-follow

# 3. Configure, pair, start
lgtv-follow init --host <TV IP> --display "<TV name in BetterDisplay>" --input HDMI_4
lgtv-follow pair      # accept the prompt on the TV (one time)
lgtv-follow install   # start now and at every login
```

That's it. Check `~/Library/Logs/lgtv-follow.log` to see it working, and give the TV a fixed IP
(a DHCP reservation on your router).

Prefer pipx? `brew install pipx python && pipx install git+https://github.com/kingsleydon/lgtv-follow`
works the same way.

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
host = "192.168.1.50"          # or a URL, e.g. "ws://192.168.1.50:3000" for older TVs

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
  Actions run one at a time, in order. A hook still running after 60 seconds is killed along
  with everything it started; to start something long-running, put it in the background (`&`).

## Good to know

- **Away from home, or the TV is off:** nothing on the Mac changes. The service retries quietly
  every few seconds and picks up as soon as the TV is back. Hotkeys give up after a few seconds
  with a one-line error.
- **Mac not plugged into the TV:** the display and audio steps are skipped.
- **No surprise prompts:** only `lgtv-follow pair` asks the TV for permission. Everything else
  uses the stored key, or refuses to connect.
- **Instant, no polling:** the TV pushes input changes over its local webOS API and the Mac
  reacts right away. A `switch` hotkey takes about a quarter of a second.
- **Looks after itself:** a dropped connection is noticed within seconds (also when the TV goes
  to standby or the Mac sleeps) and reconnected. If the service ever stops making progress, it
  exits and launchd starts it again.
- **Pairing key:** stored in `~/.config/lgtv-follow/keys.json`, readable only by you. Keys from
  older versions are carried over automatically.

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

The first line the service logs shows the version it's running and where from. See the
[changelog](CHANGELOG.md) for what's new.

## Uninstall

```sh
lgtv-follow uninstall
uv tool uninstall lgtv-follow
rm -rf ~/.config/lgtv-follow ~/.local/state/lgtv-follow ~/Library/Logs/lgtv-follow.log
```

## Development

```sh
uv sync                                               # environment from the lockfile
uv run pytest                                         # includes end-to-end tests against a fake TV
uv run ruff check . && uv run ruff format --check .
```

Dependencies are locked in `uv.lock` (CI runs `uv sync --locked`); change them with `uv add` /
`uv add --dev`. How the code fits together:

| Module | Role |
|---|---|
| `tv.py` | A small client for the TV's webOS protocol (JSON over a websocket). Every wait is bounded. |
| `fsm.py` | A pure state machine: from what the TV reports, which rules enter or leave. |
| `daemon.py` | The service: the connection lifecycle as a state loop, the follower that runs actions in order on one worker thread, and a watchdog. |
| `actions.py`, `commands.py` | What happens on the Mac: display, audio and hooks, through a runner that handles timeouts and dry runs. |
| `config.py`, `keys.py`, `history.py`, `launchd.py`, `cli.py` | Config file, pairing keys, input history for `back`/`toggle`, the LaunchAgent, and the commands. |

Talks to the TV directly over webOS's websocket protocol; the app manifest comes from
[bscpylgtv](https://github.com/chros73/bscpylgtv). MIT licensed.
