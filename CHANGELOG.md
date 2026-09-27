# Changelog

All notable changes to this project are documented here.

## v1.0.0 — First public release

Initial release of Luma: a Windows tray app for local control of Tapo bulbs
and light strips, plus a standalone command-line controller.

### Tray app

- System-tray-only presence (no taskbar window); left-click to open, click
  outside or <kbd>Esc</kbd> to dismiss.
- Tapo account sign-in with local network discovery of bulbs and light
  strips; no cloud round-trip for control.
- Saved login via Windows Credential Manager; "Forget saved login" clears it.
- Per-light controls: power, brightness, white temperature (slider plus 8
  quick shades from 2500K–6500K rendered in their real blackbody color), 24
  full-saturation color swatches, and a custom color picker.
- Two light-list layouts — Large cards and Small cards (two-column grid with
  a Details expander) — remembered between launches.
- Dedicated Reorder page for setting a manual priority order per light,
  persisted per device (by MAC address) independent of account or network.
- Party mode: synchronized random-color cycling across all online,
  color-capable lights, with a configurable interval (0.5s–5s).
- Light / Dark / Auto theme, with Auto following Windows' own setting live;
  tray icon dims/glows based on whether any light is on.
- Native C++ launcher (`Luma.exe`) instead of a bundled PyInstaller binary,
  avoiding Qt DLL packaging issues; launches `tray_app.py` under the
  project's own virtual environment.
- Optional Windows Startup shortcut for launch-at-login.

### Command-line controller

- `control.py`: `discover`, `status`, `on`, `off`, `brightness`, `white`,
  `color`, and an `interactive` REPL mode, with credentials entered
  interactively (never persisted) or via environment variables.

### Testing

- `test_backend.py`: unit coverage for discovery/authentication filtering,
  offline/recovery handling, and account-switch isolation in the backend
  scan logic.
