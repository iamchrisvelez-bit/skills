# Brainiac for Mac

Two ways to run Brainiac as an app. Both give you the same thing: Brainiac running quietly in the
background, and its console in its own app window with a Dock icon.

## Option A: build Brainiac.app (no Python needed afterwards)

On your Mac, from this folder:

```bash
./build.sh
```

The script:
1. sets up a private Python environment in `.venv`
2. draws the icon
3. bundles Brainiac with PyInstaller
4. signs the app for this Mac
5. makes a disk image

The first run takes a few minutes. You get:

- `dist/Brainiac.app`
- `dist/Brainiac.dmg`: open it and drag Brainiac to Applications.

Requirements: macOS 11 or later and Python 3.10 or later (`python3 --version`; install from python.org or with
`brew install python` if needed). Build on the kind of Mac you'll run it on: Apple silicon builds run on Apple
silicon, Intel builds on Intel.

## Option B: run from source

```bash
cd skills/brainiac
pip install -r requirements.txt
python -m brainiac app
```

## First launch

1. Open Brainiac. It starts in the background and opens its window, in Chrome, Edge or Brave as an app window
   with no browser bar. Without one of those it opens in Safari.
2. Paste your Anthropic API key when asked. Create one at console.anthropic.com → Settings → API keys. It's
   stored in your **Keychain** under "Brainiac (Anthropic API key)", never in Brainiac's files.
3. Optional: in Chrome, choose **Install Brainiac** from the address bar's install icon, or from
   ⋮ → Cast, save and share → Install page as app. Brainiac then gets its own Dock icon and Launchpad entry.

Opening Brainiac again while it's running just opens another window. Closing the window doesn't stop
Brainiac, so watchers and reminders keep working. To stop it, use **Quit Brainiac** in the console header.

## Start at login (optional)

```bash
# From source:
python -m brainiac app --login-item on      # or: off
# From the built app:
/Applications/Brainiac.app/Contents/MacOS/Brainiac app --login-item on
```

This adds a per-user LaunchAgent at `~/Library/LaunchAgents/com.brainiac.agent.plist` that starts Brainiac in
the background when you log in. Turn it off with `--login-item off`, or delete that file.

## Where things live

| What | Where |
|---|---|
| Brainiac's memory, worlds, mind, sessions, watches, connections | `~/Library/Application Support/Brainiac/` |
| API key | Keychain item "Brainiac (Anthropic API key)" |
| Log (when started at login) | `~/Library/Application Support/Brainiac/logs/brainiac.log` |

## Code that Brainiac runs

Inside the app, Brainiac's `run_python` tool uses the bundled interpreter, which has the Python standard
library only. To give Brainiac a full Python (numpy, pandas, …), set `BRAINIAC_PYTHON` to an interpreter's
path. For a login item, add it under `EnvironmentVariables` in the LaunchAgent plist.

## Sharing the app with other Macs

`build.sh` signs the app ad hoc, which is enough for the Mac that built it. Another Mac will refuse an
app downloaded from the internet unless it is signed with an Apple Developer ID and notarized. That
needs an Apple Developer account ($99 a year). Then:

```bash
codesign --force --deep --options runtime --sign "Developer ID Application: Your Name (TEAMID)" dist/Brainiac.app
ditto -c -k --keepParent dist/Brainiac.app dist/Brainiac.zip
xcrun notarytool submit dist/Brainiac.zip --apple-id you@example.com --team-id TEAMID --wait
xcrun stapler staple dist/Brainiac.app
```

## Uninstall

Quit Brainiac, run `--login-item off` if you turned it on, then delete:
- the app
- `~/Library/Application Support/Brainiac`
- the Keychain item (Keychain Access → search "Brainiac", or `brainiac key delete`)
