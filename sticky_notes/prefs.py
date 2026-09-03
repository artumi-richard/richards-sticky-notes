import json
import os
from pathlib import Path

from gi.repository import GLib

from .note import COLORS, FONT_STYLE_PROPORTIONAL

COLOR_NAMES = list(COLORS.keys())

PLACEMENT_CASCADE = "cascade"
PLACEMENT_FREE_SPACE = "free_space"

DEFAULT_COLOR_CYCLE = "cycle"

FULLSCREEN_MODE_WINDOW = "window"
FULLSCREEN_MODE_SCREEN = "screen"

ON_CLOSE_NONE = "none"
ON_CLOSE_REFLOW_GRID = "reflow_grid"

CONFIG_DIR = Path(GLib.get_user_config_dir()) / "sticky-notes"
CONFIG_FILE = CONFIG_DIR / "prefs.json"


class Preferences:
    def __init__(self):
        self.default_width = 400
        self.default_height = 300
        self.default_color = DEFAULT_COLOR_CYCLE  # a color name, or DEFAULT_COLOR_CYCLE
        self.placement_mode = PLACEMENT_CASCADE
        self.prevent_overlap = True
        self.proportional_font = "Sans 11"
        self.monospace_font = "Monospace 11"
        self.default_font_style = FONT_STYLE_PROPORTIONAL
        self.fullscreen_mode = FULLSCREEN_MODE_WINDOW
        self.on_close_action = ON_CLOSE_NONE
        self._cycle_index = 0
        self.load()

    def pick_color(self):
        if self.default_color != DEFAULT_COLOR_CYCLE:
            return self.default_color
        color = COLOR_NAMES[self._cycle_index % len(COLOR_NAMES)]
        self._cycle_index += 1
        return color

    def default_size(self):
        return (self.default_width, self.default_height)

    def to_dict(self):
        return {
            "default_width": self.default_width,
            "default_height": self.default_height,
            "default_color": self.default_color,
            "placement_mode": self.placement_mode,
            "prevent_overlap": self.prevent_overlap,
            "proportional_font": self.proportional_font,
            "monospace_font": self.monospace_font,
            "default_font_style": self.default_font_style,
            "fullscreen_mode": self.fullscreen_mode,
            "on_close_action": self.on_close_action,
        }

    def load(self):
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        self.default_width = data.get("default_width", self.default_width)
        self.default_height = data.get("default_height", self.default_height)
        self.default_color = data.get("default_color", self.default_color)
        self.placement_mode = data.get("placement_mode", self.placement_mode)
        self.prevent_overlap = data.get("prevent_overlap", self.prevent_overlap)
        self.proportional_font = data.get("proportional_font", self.proportional_font)
        self.monospace_font = data.get("monospace_font", self.monospace_font)
        self.default_font_style = data.get("default_font_style", self.default_font_style)
        self.fullscreen_mode = data.get("fullscreen_mode", self.fullscreen_mode)
        self.on_close_action = data.get("on_close_action", self.on_close_action)

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = CONFIG_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(json.dumps(self.to_dict(), indent=2))
        os.replace(tmp_file, CONFIG_FILE)
