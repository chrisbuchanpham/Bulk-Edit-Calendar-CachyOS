# Bulk Edit Calendar

A privacy-conscious Google Calendar bulk editor designed for CachyOS and other Arch-based Linux systems. It runs entirely on your computer, opens in your browser, and shows an exact preview before changing anything.

> **Alpha software:** Start with a disposable calendar and verify every preview. Calendar deletion is permanent.

## Features

- Search across multiple calendars and absolute or relative date ranges.
- Filter title, description, location, organizer, attendee, timing, recurrence, visibility, and event type.
- Preview and select exact matches before applying changes.
- Rename events, replace or append descriptions, change locations, shift times, adjust durations, change visibility, replace reminders, move events, or delete them.
- Choose selected occurrences or an entire recurring series for each operation.
- Detect events changed since preview instead of overwriting them.
- Keep one undo operation in memory for edits and moves; deletion is intentionally irreversible.
- Save reusable presets without saving Calendar event contents.
- Store Google tokens in the Linux Secret Service rather than a plaintext token file.

SMS reminders are not offered because Google Calendar no longer delivers them. Calendar moves are limited by Google to standard events.

## Install from source on CachyOS

Install system requirements:

```bash
sudo pacman -S --needed python python-pipx python-fastapi uvicorn python-jinja \
  python-pydantic python-google-api-python-client python-google-auth-oauthlib \
  python-keyring python-platformdirs
```

From a release checkout, install the application in an isolated environment:

```bash
pipx install .
bulk-edit-calendar
```

For development:

```bash
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest
.venv/bin/bulk-edit-calendar --port 0
```

## Google OAuth setup

Each user supplies their own OAuth client. Nothing is routed through a shared developer account.

1. Create or select a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Google Calendar API**.
3. Configure the Google Auth Platform consent screen for your own use. If the project is in testing, add your Google account as a test user.
4. Create an OAuth client with application type **Desktop app**.
5. Download the JSON file.
6. Start Bulk Edit Calendar, choose that JSON file, and click **Connect Google account**.

The app requests only `calendar.events` and `calendar.calendarlist.readonly`. The first permits event edits; the second lists calendars without changing subscriptions.

## Local data and security

- The server listens only on `127.0.0.1` and rejects non-loopback clients, untrusted Host headers, cross-origin writes, and missing CSRF tokens.
- OAuth client configuration is stored with user-only permissions under your XDG config directory.
- Google tokens are stored by the desktop keyring/Secret Service.
- Presets are stored in a user-only SQLite database under your XDG data directory.
- Previewed events and undo snapshots exist only in memory and disappear when the app stops or you disconnect.
- There is no telemetry.

## CachyOS package build

The included `packaging/arch/PKGBUILD` is intended for release tags. Build from its isolated directory so Arch's build workspace cannot collide with the Python `src/` directory:

```bash
cd packaging/arch
makepkg --syncdeps --install
```

The source archive is pinned by SHA-256. Increment `pkgrel` for packaging-only changes and regenerate `.SRCINFO` whenever `PKGBUILD` changes.

## Clean-room origin

This is a new implementation inspired by the workflow of [Bulk-Edit-Calendar-Events-GAS](https://github.com/derekantrican/Bulk-Edit-Calendar-Events-GAS). No source code, documentation text, assets, or Git history from that unlicensed repository are included here.

## License

MIT © 2026 Chris Buchan Pham. See [LICENSE](LICENSE).
