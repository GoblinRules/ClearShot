# ClearShot v1.3.12

## Fixed

- Fixed consecutive recording sessions so a stale finish/finalize signal from the previous recording cannot affect the next one.
- Treats a finalizing recording as active until cleanup is complete, preventing a new recording from starting in the small handoff window.
- Keeps recorder workers alive until their thread has fully finished, avoiding second-run stop state issues.

## Downloads

| File | Description |
|------|-------------|
| **ClearShot.exe** | Portable app - just run, no installation needed |
| **ClearShot_Setup_1.3.12.exe** | Full installer - Start Menu and desktop shortcuts |

## Requirements

- Windows 10/11
- No additional dependencies needed
