import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk, Pango

from . import APP_ID
from .board import BoardWindow
from .note import NOTE_CSS
from .prefs import Preferences

BOARD_CSS = """
.board-background {
    background: linear-gradient(135deg, #2e3440 0%, #4c566a 50%, #5e81ac 100%);
}

.note-card {
    border-radius: 6px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

.note-card.note-focused {
    box-shadow: 0 0 0 3px #88c0d0, 0 2px 4px rgba(0, 0, 0, 0.3);
}

.closed-swatch {
    border-radius: 3px;
}

.note-resize-grip {
    opacity: 0.45;
}

.note-resize-grip:hover {
    opacity: 0.9;
}

.note-handle {
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    background-color: rgba(0, 0, 0, 0.08);
    padding-left: 4px;
    padding-right: 4px;
}

.note-text {
    background-color: transparent;
    color: #2b2b2b;
}

.note-text text {
    background-color: transparent;
}
"""


def _font_css_rule(class_name, font_desc_str):
    desc = Pango.FontDescription.from_string(font_desc_str)
    family = (desc.get_family() or "Sans").replace('"', "")
    size = desc.get_size() / Pango.SCALE if desc.get_size() else 11
    unit = "px" if desc.get_size_is_absolute() else "pt"
    return (
        f'.{class_name}, .{class_name} text {{ '
        f'font-family: "{family}"; font-size: {size}{unit}; }}'
    )


def build_css(prefs):
    font_css = _font_css_rule(
        "note-font-proportional", prefs.proportional_font
    ) + "\n" + _font_css_rule("note-font-monospace", prefs.monospace_font)
    return NOTE_CSS + BOARD_CSS + font_css


class StickyNotesApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.board = None
        self.prefs = None
        self.css_provider = None

    def do_startup(self):
        Adw.Application.do_startup(self)

        self.prefs = Preferences()

        self.css_provider = Gtk.CssProvider()
        self.css_provider.load_from_string(build_css(self.prefs))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self.css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self.set_accels_for_action("win.new-note", ["<Control>n"])
        self.set_accels_for_action("win.close-focused-note", ["<Control>q"])
        self.set_accels_for_action("win.focus-next-note", ["<Control>Page_Down"])
        self.set_accels_for_action("win.focus-prev-note", ["<Control>Page_Up"])
        self.set_accels_for_action("win.toggle-fullscreen-note", ["F11"])
        self.set_accels_for_action("win.show-shortcuts", ["<Control>question"])

    def reload_css(self):
        self.css_provider.load_from_string(build_css(self.prefs))

    def do_activate(self):
        if self.board is None:
            self.board = BoardWindow(application=self, prefs=self.prefs)
            if not self.board.load_state():
                self.board.add_note()
            self.board.focus_initial_note()
        self.board.present()


def main():
    app = StickyNotesApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
