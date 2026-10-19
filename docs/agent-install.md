# Installing lgtv-follow: instructions for AI agents

You are setting up [lgtv-follow](https://github.com/kingsleydon/lgtv-follow) on the user's Mac.
It makes the Mac follow an LG webOS TV's input: when the TV shows the Mac's HDMI input, the TV
display is connected (via BetterDisplay) and audio goes to the TV; on any other input the display
is disconnected and audio goes back to what was used before.

Work through the steps in order. Run commands yourself; only ask the user for what you can't
find out, and for the one physical action (accepting the pairing prompt on the TV).

## Ground rules

- **Never switch the TV's input** (`lgtv-follow switch`/`toggle`) unless the user asks. They may
  be watching or playing something on another input.
- **Pairing shows a prompt on the TV.** Tell the user before running `lgtv-follow pair`, and run it
  only once, with the final TV IP. Don't try other IP addresses with `pair`: keys are stored per
  address, and every new address shows the prompt again.
- Don't change settings in other apps (launchers, BetterDisplay, router) without asking.
- If something fails, read the error and the troubleshooting section before retrying.

## 1. Prerequisites

1. Confirm this is macOS and Homebrew is installed (`brew --version`). If Homebrew is missing,
   ask the user before installing it.
2. Check that BetterDisplay is installed (`ls /Applications/BetterDisplay.app`). If it isn't, ask
   the user to install it from https://betterdisplay.pro (or offer
   `brew install --cask betterdisplay`), then open it.
3. Install the command-line tools:

   ```sh
   brew install uv betterdisplaycli switchaudio-osx
   ```

4. Check that BetterDisplay's CLI works: `betterdisplaycli get --identifiers`. If it prints
   `Failed.` or nothing, ask the user to enable **command-line integration** in BetterDisplay's
   Settings (see https://betterdisplay.pro/integration), then retry.

## 2. Install

```sh
uv tool install git+https://github.com/kingsleydon/lgtv-follow
```

The executable is `~/.local/bin/lgtv-follow`. If `lgtv-follow` isn't on PATH, run
`uv tool update-shell` or use the full path.

## 3. Gather the settings

You need three values:

- **TV IP address.** Look for the TV on the network: `arp -a | grep -i lg` (LG TVs usually show
  up as `lgwebostv`). If you find exactly one candidate, confirm it with the user; otherwise ask
  them (TV *Settings → Network*, or the router's device list). Suggest giving the TV a fixed IP
  (a DHCP reservation on the router) so it doesn't change later.
- **Display name.** From `betterdisplaycli get --identifiers`: the `name` of the TV display
  (often starts with `LG TV`). The TV must be connected to the Mac and showing it for it to appear.
- **The Mac's HDMI input.** Ask the user which HDMI port the Mac is plugged into (`HDMI_1`–`HDMI_4`),
  or determine it after pairing (step 4). If the TV is currently showing the Mac, `lgtv-follow inputs` marks
  that input with `*`.

The audio output usually has the same name as the display; check with
`SwitchAudioSource -a -t output`. If it differs, set `audio_output` in the config accordingly.

## 4. Configure and pair

```sh
lgtv-follow init --host <TV IP> --display "<display name>" --input <HDMI_n>
```

Tell the user: *"A prompt will appear on the TV — please accept it with the remote."* Then:

```sh
lgtv-follow pair
```

Then confirm the input with `lgtv-follow inputs`. If the Mac's input differs from the one you
used, rerun `init --force` with the correct `--input`.

The config lives at `~/.config/lgtv-follow/config.toml`. Rerunning `init --force` keeps the
pairing.

## 5. Install the background service and verify

```sh
lgtv-follow check     # must report config ok, both tools found, paired: yes
lgtv-follow install   # starts now and at every login
sleep 5; tail -5 ~/Library/Logs/lgtv-follow.log
```

The log should show `lgtv-follow <version> starting`, `connected to <TV IP>` and the current
`tv input`. If the TV is on the Mac's input it also shows `enter mac`; otherwise `leave mac`.

Tell the user how to test it: switch the TV to another input with the remote, then back. The
Mac's display and audio should follow each time, and the log records every change.

## 6. Optional: hotkeys

Offer to set up hotkeys for switching the TV from the Mac. The commands:

```sh
~/.local/bin/lgtv-follow switch HDMI_1   # go to an input
~/.local/bin/lgtv-follow toggle HDMI_4   # Mac ⇄ previous input (use the Mac's input)
```

Use full paths: launchers often run commands without the user's shell PATH. Ask which launcher
they use (Shortcuts, Raycast, Alfred, BetterTouchTool…) and which keys they want. For Raycast, the
repo's `contrib/script-commands` folder can be added as a script directory.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `TV not reachable at …` | TV off, on another network, or wrong IP. Check `host` in the config. Older TVs only answer on port 3000: set `host = "ws://<TV IP>:3000"`. |
| `not paired with …` | Run `lgtv-follow pair` (after telling the user about the prompt). |
| `can't follow the TV's state (…)` or `TV didn't report its power state` | The TV refuses the power/input subscriptions. Update the TV's firmware; the service keeps retrying. |
| `the TV refused: …` | The TV rejected a command; the message says why. |
| Changes don't take effect, or the log shows an old version | The first log line shows the version and path that's running. Reinstall or upgrade, then `lgtv-follow install` to restart the service. |
| `betterdisplaycli … Failed.` | Enable command-line integration in BetterDisplay's Settings; check the display name. |
| Display follows but audio doesn't | Set `audio_output` to a name from `SwitchAudioSource -a -t output`. |
| `display '…' not attached to this Mac` | The TV isn't plugged into this Mac, or the display name is wrong. |

Logs: `~/Library/Logs/lgtv-follow.log`. To watch what would happen without changing anything:
`lgtv-follow run --dry-run` (safe to run next to the service; stop it with Ctrl-C).
