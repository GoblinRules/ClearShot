# ClearShot v1.3.0

## New

- Added a distinct System audio recording mode that captures the selected Windows output device through loopback.
- Kept microphone capture as a separate Microphone input mode with its own input-device selector.
- Added live recording annotation tools from the tray menu while recording.
- Added pen, line, arrow, rectangle, highlight, ellipse, text, and numbered marker tools for live recordings.
- Added undo and clear controls for live recording annotations.

## Improved

- Updated Settings so recording audio is clearly split into No audio, Microphone input, and System audio.
- Migrated older enabled-audio settings to Microphone input mode automatically.
- Updated Help/About and README documentation for recording audio modes and live recording annotations.

## Downloads

| File | Description |
|------|-------------|
| **ClearShot.exe** | Portable app - just run, no installation needed |
| **ClearShot_Setup_1.3.0.exe** | Full installer - Start Menu, desktop shortcut, auto-start option |

## Requirements

- Windows 10/11
- No additional dependencies needed

## Notes

- System audio records from the selected Windows output device. The default output device is used unless another output is selected.
- Microphone recording still uses Windows DirectShow input devices.
- Live recording annotations are captured into the video because they are drawn over the active recording area.
