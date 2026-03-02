# ClearShot v1.0.4

## 🔧 Improvement

- **Replaced hotkey system with Win32 RegisterHotKey API** — Global hotkeys now use the native Windows `RegisterHotKey` API instead of the Python `keyboard` module. This fixes two issues:
  - **Hotkeys no longer leak to other apps** — pressing your screenshot shortcut in Chrome (or any app) will no longer trigger that app's own shortcuts (e.g. DevTools opening with Ctrl+Shift+I)
  - **No more stuck modifier keys** — Ctrl, Shift, and Alt keys no longer get "stuck" after using a hotkey
- **Removed `keyboard` module dependency** — one fewer external dependency, smaller build

## 📥 Downloads

| File | Description |
|------|-------------|
| **ClearShot.exe** | Portable — just run, no installation needed |
| **ClearShot_Setup_1.0.4.exe** | Installer — Start Menu, desktop shortcut, auto-start option |

## 📋 Requirements

- Windows 10/11
- No additional dependencies needed
