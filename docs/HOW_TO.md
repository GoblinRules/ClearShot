# How to use ClearShot

[README](../README.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Install and start

1. Open the [latest release](https://github.com/GoblinRules/ClearShot/releases/latest).
2. Download `ClearShot_Setup_<version>.exe` for the recommended installer, or `ClearShot_Portable_<version>.zip` to run without installing.
3. Run the installer, or extract the entire ZIP and run `ClearShot.exe`. Keep `_internal` beside the portable EXE.
4. Find ClearShot in the Windows tray beside the clock. Check the hidden-icons arrow if necessary.

The standalone `ClearShot.exe` download is another portable option. It extracts a runtime into Windows Temp while running. Packaged downloads need no separate Python installation.

## Take a screenshot

1. Press `Print Screen` or select **Capture Region** from the tray menu.
2. Click and drag to select an area.
3. Release the mouse and choose an action:

| Action | Result |
| --- | --- |
| Copy | Copies the image to the clipboard for pasting elsewhere |
| Save | Opens a dialog to choose a destination |
| Quick Save | Uses your configured folder, format, and filename pattern |
| Edit | Opens the annotation editor |
| Cancel | Discards the selection |

For a fullscreen screenshot, press `Ctrl + Print Screen`. The tray's **Capture Fullscreen** menu lets you choose all monitors or a particular display.

## Edit a screenshot

Choose **Edit** after selecting a region. Select a tool, color, and size, then draw on the image.

| Tool | Use |
| --- | --- |
| Pen | Freehand marks |
| Line / Arrow | Connect details or point to an item |
| Rectangle / Filled Rectangle / Ellipse | Outline or cover an area |
| Text | Add labels |
| Blur | Visually obscure an area |
| Counter | Add numbered steps |

Use **Undo**, **Redo**, or **Clear** to revise your edits, then copy or save. For sensitive text, prefer an opaque filled rectangle and inspect the saved image; blur alone is not reliable redaction.

## Set up recording and audio

1. Open **Settings > General**.
2. Choose a writable recording folder with enough disk space.
3. Select **MP4** or **MKV** and a frame rate: **10**, **15**, **20**, or **30** FPS. The default is 15 FPS; higher rates require more resources.
4. Choose an audio mode:

| Mode | What to configure |
| --- | --- |
| No audio | Nothing else; the recording is silent (default) |
| Microphone input | Select the microphone you want to capture |
| System audio | Select the output device playing the sound, such as speakers or a headset |

Only one mode is used at a time; simultaneous microphone/system-audio mixing is not offered. After reconnecting devices, use the refresh button and check your selection. Missing devices are marked unavailable; ClearShot does not silently choose another microphone.

Save the settings, then make a short recording and play it back before an important session.

## Record, pause, and stop

1. Right-click the tray icon and open **Screen Record**.
2. Choose **Record Region**, **Record All Monitors**, or a display under **Record Monitor**. For a region, drag to select the area; recording starts after selection.
3. Pause/resume using the floating controls, tray menu, or `Ctrl + Alt + Shift + P`.
4. Stop using **Stop Recording** or `Ctrl + Alt + Shift + X`.
5. Wait for finalizing/exporting to complete and the saved-file confirmation.

Pausing excludes audio and video and freezes the REC timer. Under capture load, frames can repeat to preserve playback duration. Floating controls are designed to stay out of the recorded video.

### Draw during recording

Show the annotation tools from the recording controls or tray menu. Select a tool and hold the configured annotation input key (default `Ctrl + Alt`) while drawing. Release it to interact normally with the desktop. Live annotations become part of the video, not a separate editable layer.

## Customize and find files

Open **Settings** from the tray:

| Tab | Purpose |
| --- | --- |
| General | Save folders, formats, filename pattern, recording frame rate/audio/border, annotation hold key, and capture preferences |
| Hotkeys | Screenshot, recording pause/resume, and stop shortcuts |
| Startup | Launch with Windows |
| About | Application information |

Default locations:

| Item | Location |
| --- | --- |
| Screenshots | `%USERPROFILE%\Pictures\ClearShot` |
| Recordings | `%USERPROFILE%\Pictures\ClearShot\Recordings` |
| Settings | `%APPDATA%\ClearShot\settings.json` |
| Logs | `%LOCALAPPDATA%\ClearShot\logs` |

Custom media folders override the defaults. The screenshot filename pattern defaults to `ClearShot_{timestamp}`. Keep the timestamp token to distinguish captures. Empty or unwritable folders are rejected when saving settings.

## Exit, upgrade, and back up settings

Stop recording and wait for export, then select **Exit** from the tray. Run the new installer or extract the new portable ZIP into a fresh folder. Settings live outside the application folder, including for portable builds. To back them up, exit ClearShot and copy `settings.json` somewhere safe.

If saving fails, follow the [recovery guide](TROUBLESHOOTING.md#recover-a-failed-recording) before deleting working files.
