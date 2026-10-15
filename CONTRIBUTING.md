# Developing and contributing

[README](README.md)

## Run from source

Use Windows 10/11 and Python 3.10 or newer. Windows APIs are required for capture, clipboard, audio, tray, and hotkey integrations.

In PowerShell:

```powershell
git clone https://github.com/GoblinRules/ClearShot.git
cd ClearShot
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Using the environment's Python directly avoids changing script execution policy. Exit installed ClearShot instances first. Source runs share the same per-user settings; back up `%APPDATA%\ClearShot\settings.json` if needed.

## Verify changes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These optional checks use your real screen/audio devices. Close private content and exit other ClearShot instances first:

```powershell
# Real capture, pause/resume, consecutive sessions, and quitting during capture
.\.venv\Scripts\python.exe tests/smoke_app.py

# Briefly records connected microphones and default system audio
.\.venv\Scripts\python.exe tests/smoke_recording_audio.py --hardware
```

The smoke checks use temporary test media. Inspect failures for leftover files. Also verify affected tray menus, settings, overlays, and packaged behavior manually.

## Build packages

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller build.spec --clean -y
```

Outputs are `dist/ClearShot.exe` (standalone) and `dist/ClearShot/` (complete runtime folder). Compile `installer.iss` with Inno Setup 6 to create the installer in `installer_output/`. Archive the complete `dist/ClearShot/` folder, including `_internal`, for the portable ZIP.

For releases, align versions in `constants.py` and `installer.iss`, update `RELEASE_NOTES.md`, and check packaged startup, recording, shutdown, and upgrade behavior. Publish binaries as release assets rather than adding new generated files to the source tree. Include SHA-256 hashes, which can be calculated with PowerShell's `Get-FileHash -Algorithm SHA256`.

## Source map

| Files | Responsibility |
| --- | --- |
| `main.py`, `app.py` | Startup, single-instance coordination, tray menus, and orchestration |
| `capture.py`, `overlay.py` | Screenshots and region selection |
| `annotator.py`, `tools.py` | Screenshot editing |
| `recording.py`, `recording_backend.py` | Recording UI, capture, audio, and export |
| `settings_window.py`, `config.py`, `constants.py` | Settings UI, persistence, and defaults |
| `diagnostics.py` | Local logs and crash diagnostics |
| `build.spec`, `installer.iss` | Packaging |
| `tests/` | Regression and opt-in smoke checks |

## Submit a change

Open an issue or focused pull request explaining the problem, changed behavior, and verification performed. Add regression coverage for behavioral fixes where practical. Do not commit private settings, recordings, logs, virtual environments, or generated packages.

For documentation changes, check links and confirm instructions against the current UI/source. See [bug-report guidance](docs/TROUBLESHOOTING.md#logs-and-bug-reports).
