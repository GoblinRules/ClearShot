"""ClearShot — JSON-based settings persistence."""

import json
import os
from constants import (
    APPDATA_DIR,
    CONFIG_FILE,
    DEFAULT_SAVE_DIR,
    DEFAULT_HOTKEYS,
    DEFAULT_PEN_COLOR,
    DEFAULT_PEN_WIDTH,
    DEFAULT_FONT_SIZE,
)

DEFAULT_SETTINGS = {
    "save_path": DEFAULT_SAVE_DIR,
    "image_format": "PNG",
    "filename_pattern": "ClearShot_{timestamp}",
    "hotkeys": DEFAULT_HOTKEYS.copy(),
    "start_with_windows": False,
    "show_tray_notifications": True,
    "pen_color": DEFAULT_PEN_COLOR,
    "pen_width": DEFAULT_PEN_WIDTH,
    "font_size": DEFAULT_FONT_SIZE,
    "copy_to_clipboard_on_save": True,
    "show_magnifier": True,
    "play_sound": False,
}


class Config:
    """Manages application settings with JSON file persistence."""

    def __init__(self):
        self._settings = DEFAULT_SETTINGS.copy()
        self._ensure_dirs()
        self.load()

    def _ensure_dirs(self):
        """Create required directories if they don't exist."""
        os.makedirs(APPDATA_DIR, exist_ok=True)
        os.makedirs(self.get("save_path", DEFAULT_SAVE_DIR), exist_ok=True)

    def load(self):
        """Load settings from the JSON config file."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # Merge with defaults (so new keys are always present)
                for key, value in DEFAULT_SETTINGS.items():
                    if key not in saved:
                        saved[key] = value
                    elif key == "hotkeys" and isinstance(value, dict):
                        for hk_key, hk_val in value.items():
                            if hk_key not in saved[key]:
                                saved[key][hk_key] = hk_val
                self._settings = saved
            except (json.JSONDecodeError, IOError):
                self._settings = DEFAULT_SETTINGS.copy()
        self._ensure_dirs()

    def save(self):
        """Persist current settings to the JSON config file."""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except IOError as e:
            print(f"Failed to save config: {e}")

    def get(self, key, default=None):
        """Get a setting value."""
        return self._settings.get(key, default)

    def set(self, key, value):
        """Set a setting value and persist."""
        self._settings[key] = value
        self.save()

    def get_hotkey(self, action):
        """Get the hotkey binding for a specific action."""
        hotkeys = self._settings.get("hotkeys", DEFAULT_HOTKEYS)
        return hotkeys.get(action, DEFAULT_HOTKEYS.get(action))

    def set_hotkey(self, action, key_combo):
        """Set the hotkey binding for a specific action."""
        if "hotkeys" not in self._settings:
            self._settings["hotkeys"] = DEFAULT_HOTKEYS.copy()
        self._settings["hotkeys"][action] = key_combo
        self.save()

    def reset(self):
        """Reset all settings to defaults."""
        self._settings = DEFAULT_SETTINGS.copy()
        self.save()

    @property
    def all_settings(self):
        """Return a copy of all settings."""
        return self._settings.copy()
