# ClearShot v1.3.13

## Fixed

- The full installer now installs the runtime alongside the app. Installed copies no longer unpack into a new `_MEI` temporary folder on each launch, and temp-folder cleaners cannot remove their runtime dependencies.
- Reduced bundled dependencies by collecting only the Qt modules used by ClearShot.
- Fixed shutdown while recording: the app stays responsive and retains recording workers until finalization finishes, avoiding destruction of a running Qt thread.
- Fixed hotkey shutdown during startup and corrected Windows handle declarations for the single-instance check. Duplicate launches exit immediately.
- Installer upgrades request a clean exit instead of force-killing ClearShot. Older versions must be exited from the tray before upgrading.
- Microphone recording continuously drains encoder errors and reaps the encoder on capture failures.
- Recording checks available space on the save drive and reports an error below 256 MB free.
- Added rotating local application logs and native crash diagnostics under `%LOCALAPPDATA%\ClearShot\logs`.

## Downloads

| File | Description |
|------|-------------|
| **ClearShot_Setup_1.3.13.exe** | Recommended full installer; runs without temporary runtime extraction |
| **ClearShot_Portable_1.3.13.zip** | Extract the complete folder and run ClearShot.exe; no temporary runtime extraction |
| **ClearShot.exe** | Standalone portable EXE; still extracts a smaller runtime while running |

## Notes

- Exit any older ClearShot instance before installing this update.
- Single-file portable apps use a launcher plus an application process. That pair is expected; it does not indicate a restart loop.
- `_MEI` folders can belong to any PyInstaller application. Do not delete an active application's runtime folder, or assume every `_MEI` folder belongs to ClearShot.

## Requirements

- Windows 10/11
- No additional dependencies needed
