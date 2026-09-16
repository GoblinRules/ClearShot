# ClearShot v1.3.14

## Fixed

- Recording and export processes now have bounded waits, continuously drained diagnostics, and checked exit codes. A stalled encoder cannot leave Stop waiting forever, and a failed encoder no longer reports a successful save.
- Audio or export failures retain intermediate video/audio in a clearly reported recovery folder inside the selected recording directory. Successful exports clean up their working files.
- Microphone and system audio now follow the same pause-aware timeline as video. Audio capture is reopened after a pause so paused audio is not buffered into the resumed recording.
- Slow screen capture repeats frames to preserve elapsed duration instead of producing sped-up videos. Excessive encoder lag stops with an actionable error.
- Microphone selection now uses Windows audio endpoint IDs, supports existing friendly-name selections, marks disconnected devices unavailable, and includes an MDI refresh button. Device availability is checked before recording.
- Empty or unwritable save locations are rejected before settings are saved. Legacy blank paths recover to defaults, and disconnected save drives no longer prevent startup.
- The REC counter excludes paused time. Stop continues to show finalizing/exporting status until saving completes.

## Verification

- Automated regression coverage for encoder errors and timeouts, failed-export recovery, audio disconnects, pause privacy, slow capture timing, settings validation, device refresh, and consecutive sessions.
- MP4/MKV exports verified with microphone and system-audio test sources.
- Local hardware checks covered three microphone inputs (including a mono endpoint) and default system audio, with pause/resume and decoded output.
- Real screen-capture tests cover consecutive recordings and quitting during capture.

## Downloads

| File | Description |
|------|-------------|
| **ClearShot_Setup_1.3.14.exe** | Recommended full installer; runtime stays in the install directory |
| **ClearShot_Portable_1.3.14.zip** | Extract the complete folder and run ClearShot.exe |
| **ClearShot.exe** | Standalone portable EXE; extracts a temporary runtime while running |
| **SHA256SUMS.txt** | Checksums for the downloads |

## Notes

- Close older copies of ClearShot before upgrading. The installer requests a clean shutdown from recent versions.
- After reconnecting a microphone, refresh audio devices in Settings and choose the required input.
- Failed/interrupted recordings may leave a `ClearShot_recovery_*` folder beside your recordings. Recover any needed media before deleting it; do not delete an active recording's folder.
- Temporary stereo audio uses about 660 MiB per recording hour. Allow space for the working files and final export.
- The installer and portable ZIP do not extract runtime files into Windows Temp. A standalone portable EXE normally has a launcher and an application process.
- Windows 10/11; no additional dependencies needed.
