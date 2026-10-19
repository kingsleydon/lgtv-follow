# Changelog

All notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- Dependencies are locked in `uv.lock`, and CI installs from it (`uv sync --locked`).
- Development tools are in a `dev` dependency group (`uv sync`) instead of a `test` extra.

## [0.3.0] - 2026-10-19

### Changed
- lgtv-follow talks to the TV itself, over webOS's websocket protocol, instead of through
  bscpylgtv. Its only dependency is now `websockets`.
- The pairing key is stored in `~/.config/lgtv-follow/keys.json`, readable only by you. The key
  from earlier versions (`tv-key.sqlite`) is imported automatically, so there's no need to pair
  again; the old file can be deleted afterwards.
- Connections to the TV ignore proxy settings in the environment.

### Added
- `[tv] host` can be a full URL, e.g. `ws://192.168.1.50:3000` for older TVs.

## [0.2.0] - 2026-10-18

### Fixed
- The service could stop following the TV after it powered off, until restarted. It now notices
  dropped connections within seconds (also in standby and after the Mac sleeps), every wait is
  bounded, and if it ever stops making progress it exits so launchd starts it again.
- Audio returns to the previous output reliably on leave.
- A stuck command or hook no longer holds up everything after it: commands time out, and a hook
  running longer than 60 seconds is killed along with everything it started.
- Hotkey commands (`switch`, `toggle`, `inputs`) give up after a few seconds instead of hanging.

### Changed
- Nothing is done until the TV reports its power state, so a TV in standby (which still reports
  its last input) is never mistaken for showing it.
- Actions always run one at a time, in order.
- The config is checked more strictly: duplicate rule names, non-string values and an empty host
  are rejected.
- The service logs its version and where it runs from when it starts.

## [0.1.0] - 2026-10-10

First release.

[Unreleased]: https://github.com/kingsleydon/lgtv-follow/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/kingsleydon/lgtv-follow/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kingsleydon/lgtv-follow/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kingsleydon/lgtv-follow/releases/tag/v0.1.0
