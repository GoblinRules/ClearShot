# Troubleshooting ClearShot

[README](../README.md) · [How-to guide](HOW_TO.md)

## No window appears

ClearShot runs in the tray. Check beside the Windows clock and inside the hidden-icons menu. Only one instance runs at a time; a second launch exits. With the portable ZIP, extract the entire archive and keep `_internal` beside `ClearShot.exe`.

## Print Screen opens another tool

Windows or another utility may use the same shortcut. Change ClearShot's binding in **Settings > Hotkeys**, or disable the competing shortcut. Check Windows **Settings > Accessibility > Keyboard** for its Print Screen screen-snipping option. Tray-menu capture also works without a hotkey.

## Missing or incorrect audio

1. Check **Settings > General**: **No audio** is the default.
2. For a microphone, choose **Microphone input** and the intended device. Check Windows microphone privacy permissions for desktop apps and input levels.
3. For playback sound, choose **System audio** and the output device actually playing it. Headsets and speakers may be separate endpoints.
4. Refresh the lists after reconnecting hardware and replace unavailable selections.
5. Record a short test and play it with the player unmuted.

Microphone and system audio cannot be combined in the current audio selector.

## Stop shows finalizing or exporting

Allow the encoder to finish, especially for long recordings with audio. Progress monitoring detects stalled exports, but completion time depends on recording size and machine speed. Avoid forcing the app closed while saving. If an error appears, retain the recovery folder it identifies.

## Recover a failed recording

Working files live in a `ClearShot_recovery_*` folder inside your recording save directory. Successful exports remove it. Failed capture/audio/export operations retain available files and report the location.

1. Wait for recording/finalization to stop, then exit ClearShot.
2. Find the folder identified by the error and copy it somewhere safe.
3. Try opening `video.mkv` in a compatible player; it may contain usable silent video.
4. Keep `audio.wav`, if present, for possible recovery in an audio/video editor.
5. Delete that recovery folder only after recovering what you need and closing ClearShot.

Interrupted files may be incomplete. Full recovery is not guaranteed. Never remove an active recording's working folder.

## Choppy video

Lower the recording frame rate, capture a smaller region or single monitor, and close resource-heavy applications. Save to a drive with sufficient free space. Repeated frames preserve elapsed duration under load but cannot restore motion that was not captured.

## Save folders and disk space

Choose a writable folder on an accessible drive in **Settings > General**. Reconnect removable drives before saving there. An unavailable save drive does not prevent startup.

Allow room for working video, uncompressed temporary audio (about 660 MiB per hour), and final export. Recording stops with an error when free space drops below the app's 256 MB threshold.

## Temp folders and two processes

The standalone EXE extracts a temporary runtime and normally has launcher and application processes. Use the installer or portable ZIP to run the runtime from its own folder. Do not delete `_MEI` directories used by running applications; other PyInstaller applications use the same naming convention.

## Logs and bug reports

Logs are stored in `%LOCALAPPDATA%\ClearShot\logs`. The main log rotates at 1 MB with three backups; native crash reports retain the current and previous run. Logs are not uploaded automatically.

Open a [GitHub issue](https://github.com/GoblinRules/ClearShot/issues) with:

- ClearShot version and package type (installer, ZIP, standalone, or source).
- Windows version, monitor setup, and reproduction steps.
- Expected behavior, actual behavior, and exact error text.
- For recordings: format, FPS, audio mode/device, duration, and whether you paused.
- Relevant log excerpts after reviewing them for private information.

Avoid posting private recordings or your entire settings file unnecessarily.
