# ClearShot v1.0.3

## 🐛 Bug Fix

- **Fixed Sticky Modifier Keys** — Resolved an issue where Ctrl and Shift keys would get "stuck" after using the screenshot hotkey, preventing Ctrl+Click and other modifier combinations from working in other applications. Root cause was `suppress=True` on global hotkey registration swallowing key events at the OS level.

## 📥 Downloads

| File | Description |
|------|-------------|
| **ClearShot.exe** | Portable — just run, no installation needed |
| **ClearShot_Setup_1.0.3.exe** | Installer — Start Menu, desktop shortcut, auto-start option |

## 📋 Requirements

- Windows 10/11
- No additional dependencies needed
