import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango

from .note import FONT_STYLE_MONOSPACE, FONT_STYLE_PROPORTIONAL, MIN_NOTE_HEIGHT, MIN_NOTE_WIDTH
from .prefs import (
    COLOR_NAMES,
    DEFAULT_COLOR_CYCLE,
    FULLSCREEN_MODE_SCREEN,
    FULLSCREEN_MODE_WINDOW,
    ON_CLOSE_NONE,
    ON_CLOSE_REFLOW_GRID,
    PLACEMENT_CASCADE,
    PLACEMENT_FREE_SPACE,
)

COLOR_LABELS = [name.capitalize() for name in COLOR_NAMES] + ["Cycle through colors"]
COLOR_VALUES = COLOR_NAMES + [DEFAULT_COLOR_CYCLE]

PLACEMENT_LABELS = ["Cascade", "Next Free Space"]
PLACEMENT_VALUES = [PLACEMENT_CASCADE, PLACEMENT_FREE_SPACE]

FONT_STYLE_LABELS = ["Proportional", "Monospace"]
FONT_STYLE_VALUES = [FONT_STYLE_PROPORTIONAL, FONT_STYLE_MONOSPACE]

FULLSCREEN_MODE_LABELS = ["Fill Window", "Fill Entire Screen"]
FULLSCREEN_MODE_VALUES = [FULLSCREEN_MODE_WINDOW, FULLSCREEN_MODE_SCREEN]

ON_CLOSE_LABELS = ["Do Nothing", "Re-arrange Remaining Notes in a Grid"]
ON_CLOSE_VALUES = [ON_CLOSE_NONE, ON_CLOSE_REFLOW_GRID]


def build_preferences_window(prefs, app):
    window = Adw.PreferencesWindow()
    window.set_title("Sticky Notes Preferences")
    window.set_default_size(560, 520)

    page = Adw.PreferencesPage()
    window.add(page)

    group = Adw.PreferencesGroup()
    group.set_title("New Note Defaults")
    page.add(group)

    def set_and_save(attr, value):
        setattr(prefs, attr, value)
        prefs.save()

    width_row = Adw.SpinRow(
        title="Default Width",
        adjustment=Gtk.Adjustment(
            value=prefs.default_width,
            lower=MIN_NOTE_WIDTH,
            upper=800,
            step_increment=10,
            page_increment=50,
        ),
    )
    width_row.connect(
        "notify::value", lambda row, _p: set_and_save("default_width", int(row.get_value()))
    )
    group.add(width_row)

    height_row = Adw.SpinRow(
        title="Default Height",
        adjustment=Gtk.Adjustment(
            value=prefs.default_height,
            lower=MIN_NOTE_HEIGHT,
            upper=800,
            step_increment=10,
            page_increment=50,
        ),
    )
    height_row.connect(
        "notify::value", lambda row, _p: set_and_save("default_height", int(row.get_value()))
    )
    group.add(height_row)

    color_row = Adw.ComboRow(title="Default Color")
    color_row.set_model(Gtk.StringList.new(COLOR_LABELS))
    color_row.set_selected(COLOR_VALUES.index(prefs.default_color))
    color_row.connect(
        "notify::selected",
        lambda row, _p: set_and_save("default_color", COLOR_VALUES[row.get_selected()]),
    )
    group.add(color_row)

    placement_row = Adw.ComboRow(title="Initial Placement")
    placement_row.set_model(Gtk.StringList.new(PLACEMENT_LABELS))
    placement_row.set_selected(PLACEMENT_VALUES.index(prefs.placement_mode))
    placement_row.connect(
        "notify::selected",
        lambda row, _p: set_and_save("placement_mode", PLACEMENT_VALUES[row.get_selected()]),
    )
    group.add(placement_row)

    layout_group = Adw.PreferencesGroup()
    layout_group.set_title("Layout")
    page.add(layout_group)

    overlap_row = Adw.SwitchRow(
        title="Prevent Notes Overlapping",
        subtitle="Dragging or resizing stops short of covering another note",
        active=prefs.prevent_overlap,
    )
    overlap_row.connect(
        "notify::active", lambda row, _p: set_and_save("prevent_overlap", row.get_active())
    )
    layout_group.add(overlap_row)

    fullscreen_row = Adw.ComboRow(title="Note Fullscreen")
    fullscreen_row.set_model(Gtk.StringList.new(FULLSCREEN_MODE_LABELS))
    fullscreen_row.set_selected(FULLSCREEN_MODE_VALUES.index(prefs.fullscreen_mode))
    fullscreen_row.connect(
        "notify::selected",
        lambda row, _p: set_and_save(
            "fullscreen_mode", FULLSCREEN_MODE_VALUES[row.get_selected()]
        ),
    )
    layout_group.add(fullscreen_row)

    on_close_row = Adw.ComboRow(title="On Note Close")
    on_close_row.set_model(Gtk.StringList.new(ON_CLOSE_LABELS))
    on_close_row.set_selected(ON_CLOSE_VALUES.index(prefs.on_close_action))
    on_close_row.connect(
        "notify::selected",
        lambda row, _p: set_and_save("on_close_action", ON_CLOSE_VALUES[row.get_selected()]),
    )
    layout_group.add(on_close_row)

    font_group = Adw.PreferencesGroup()
    font_group.set_title("Fonts")
    page.add(font_group)

    def set_font_and_reload(attr, font_desc):
        set_and_save(attr, font_desc.to_string())
        app.reload_css()

    def make_font_row(title, attr):
        row = Adw.ActionRow(title=title)
        row.set_subtitle(getattr(prefs, attr))
        change_button = Gtk.Button(icon_name="document-edit-symbolic")
        change_button.add_css_class("flat")
        change_button.set_valign(Gtk.Align.CENTER)
        change_button.set_tooltip_text("Change Font")

        def on_clicked(_button):
            dialog = Gtk.FontDialog()
            initial = Pango.FontDescription.from_string(getattr(prefs, attr))

            def on_chosen(dlg, result):
                try:
                    desc = dlg.choose_font_finish(result)
                except GLib.Error:
                    return
                if desc is not None:
                    set_font_and_reload(attr, desc)
                    row.set_subtitle(desc.to_string())

            dialog.choose_font(window, initial, None, on_chosen)

        change_button.connect("clicked", on_clicked)
        row.add_suffix(change_button)
        return row

    font_group.add(make_font_row("Proportional Font", "proportional_font"))
    font_group.add(make_font_row("Monospace Font", "monospace_font"))

    font_style_row = Adw.ComboRow(title="New Notes Use")
    font_style_row.set_model(Gtk.StringList.new(FONT_STYLE_LABELS))
    font_style_row.set_selected(FONT_STYLE_VALUES.index(prefs.default_font_style))
    font_style_row.connect(
        "notify::selected",
        lambda row, _p: set_and_save(
            "default_font_style", FONT_STYLE_VALUES[row.get_selected()]
        ),
    )
    font_group.add(font_style_row)

    return window
