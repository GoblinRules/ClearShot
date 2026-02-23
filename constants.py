"""ClearShot — Application constants and defaults."""

import os

APP_NAME = "ClearShot"
APP_VERSION = "1.0.0"
APP_AUTHOR = "ClearShot"

# Paths
APPDATA_DIR = os.path.join(os.environ.get("APPDATA", ""), APP_NAME)
CONFIG_FILE = os.path.join(APPDATA_DIR, "settings.json")
DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "ClearShot")

# Mutex name for single-instance lock
MUTEX_NAME = "ClearShot_SingleInstance_Mutex"

# Default hotkeys
DEFAULT_HOTKEYS = {
    "region_capture": "print screen",
    "fullscreen_capture": "ctrl+print screen",
}

# Image format options
IMAGE_FORMATS = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "BMP": ".bmp",
}

# Annotation defaults
DEFAULT_PEN_COLOR = "#FF0000"
DEFAULT_PEN_WIDTH = 3
DEFAULT_FONT_SIZE = 16
DEFAULT_FONT_FAMILY = "Arial"

# Color palette for annotation tools
COLOR_PALETTE = [
    "#FF0000",  # Red
    "#FF6600",  # Orange
    "#FFCC00",  # Yellow
    "#00CC00",  # Green
    "#0099FF",  # Blue
    "#9933FF",  # Purple
    "#FF33CC",  # Pink
    "#FFFFFF",  # White
    "#000000",  # Black
    "#888888",  # Gray
]

# Tool identifiers
TOOL_PEN = "pen"
TOOL_LINE = "line"
TOOL_ARROW = "arrow"
TOOL_RECT = "rect"
TOOL_FILLED_RECT = "filled_rect"
TOOL_ELLIPSE = "ellipse"
TOOL_TEXT = "text"
TOOL_BLUR = "blur"
TOOL_COUNTER = "counter"
