import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk, Pango

from .colors import DEFAULT_BACKGROUND, all_schemes, apply_scheme, new_slot_id

from .note import FONT_STYLE_MONOSPACE, FONT_STYLE_PROPORTIONAL, MIN_NOTE_HEIGHT, MIN_NOTE_WIDTH
from .prefs import (
    DEFAULT_COLOR_CYCLE,
    FULLSCREEN_MODE_SCREEN,
    FULLSCREEN_MODE_WINDOW,
    ON_CLOSE_NONE,
    ON_CLOSE_REFLOW_GRID,
    PLACEMENT_CASCADE,
    PLACEMENT_FREE_SPACE,
)

PLACEMENT_LABELS = ["Cascade", "Next Free Space"]
PLACEMENT_VALUES = [PLACEMENT_CASCADE, PLACEMENT_FREE_SPACE]

FONT_STYLE_LABELS = ["Proportional", "Monospace"]
FONT_STYLE_VALUES = [FONT_STYLE_PROPORTIONAL, FONT_STYLE_MONOSPACE]

FULLSCREEN_MODE_LABELS = ["Fill Window", "Fill Entire Screen"]
FULLSCREEN_MODE_VALUES = [FULLSCREEN_MODE_WINDOW, FULLSCREEN_MODE_SCREEN]

ON_CLOSE_LABELS = ["Do Nothing", "Re-arrange Remaining Notes in a Grid"]
ON_CLOSE_VALUES = [ON_CLOSE_NONE, ON_CLOSE_REFLOW_GRID]


def build_preferences_window(prefs, app, board):
    window = Adw.PreferencesWindow()
    window.set_title("Sticky Notes Preferences")
    window.set_default_size(680, 620)

    page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
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
    color_values = []
    syncing_color_row = False

    def refresh_color_row():
        nonlocal color_values, syncing_color_row
        color_values = prefs.palette_ids() + [DEFAULT_COLOR_CYCLE]
        labels = [slot["name"] for slot in prefs.palette] + ["Cycle through colors"]
        selected = (
            color_values.index(prefs.default_color)
            if prefs.default_color in color_values
            else len(color_values) - 1
        )
        syncing_color_row = True
        color_row.set_model(Gtk.StringList.new(labels))
        color_row.set_selected(selected)
        syncing_color_row = False

    def on_default_color_selected(row, _p):
        if syncing_color_row:
            return
        index = row.get_selected()
        if 0 <= index < len(color_values):
            set_and_save("default_color", color_values[index])

    refresh_color_row()
    color_row.connect("notify::selected", on_default_color_selected)
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
    def on_overlap_toggled(row, _p):
        set_and_save("prevent_overlap", row.get_active())
        board.set_cascade_enabled(not row.get_active())

    overlap_row.connect("notify::active", on_overlap_toggled)
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

    spacing_row = Adw.SpinRow(
        title="Grid Spacing",
        subtitle="Used for note placement margins, cascading, arranging, and drag-snapping",
        adjustment=Gtk.Adjustment(
            value=prefs.grid_spacing,
            lower=1,
            upper=200,
            step_increment=5,
            page_increment=20,
        ),
    )
    spacing_row.connect(
        "notify::value", lambda row, _p: set_and_save("grid_spacing", int(row.get_value()))
    )
    layout_group.add(spacing_row)

    margin_row = Adw.SpinRow(
        title="Grid Margin",
        subtitle="Gap kept inside each grid line — e.g. spacing 20 + margin 5 "
        "gives a 90px note spanning 5 grid cells (5×20 − 5 − 5)",
        adjustment=Gtk.Adjustment(
            value=prefs.grid_margin,
            lower=0,
            upper=100,
            step_increment=1,
            page_increment=5,
        ),
    )
    margin_row.connect(
        "notify::value", lambda row, _p: set_and_save("grid_margin", int(row.get_value()))
    )
    layout_group.add(margin_row)

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

    window.add(_build_colors_page(window, prefs, app, refresh_color_row))

    return window


def _hex_to_rgba(hex_color):
    rgba = Gdk.RGBA()
    rgba.parse(hex_color)
    return rgba


def _rgba_to_hex(rgba):
    return "#{:02x}{:02x}{:02x}".format(
        *(round(max(0.0, min(1.0, c)) * 255) for c in (rgba.red, rgba.green, rgba.blue))
    )


def _lerp_stops(stops, t):
    """Colour at position ``t`` (0..1) along evenly spaced gradient ``stops``."""
    if len(stops) == 1:
        return stops[0]
    pos = t * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    f = pos - i
    a, b = stops[i], stops[i + 1]
    rgba = Gdk.RGBA()
    rgba.red = a.red + (b.red - a.red) * f
    rgba.green = a.green + (b.green - a.green) * f
    rgba.blue = a.blue + (b.blue - a.blue) * f
    rgba.alpha = 1.0
    return rgba


class _SchemePreview(Gtk.Widget):
    """A miniature board: the scheme's background with its note colours on top."""

    SLICES = 32

    def __init__(self, colors, background, width=104, height=26):
        super().__init__()
        self._rgbas = [_hex_to_rgba(c) for c in colors]
        self._background = [_hex_to_rgba(c) for c in background]
        self.set_size_request(width, height)
        self.set_valign(Gtk.Align.CENTER)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.add_css_class("swatch-strip")

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        slice_w = w / self.SLICES
        for i in range(self.SLICES):
            color = _lerp_stops(self._background, (i + 0.5) / self.SLICES)
            snapshot.append_color(color, Graphene.Rect().init(i * slice_w, 0, slice_w + 0.5, h))

        pad, gap = 5, 2
        n = max(1, len(self._rgbas))
        step = (w - 2 * pad + gap) / n
        for i, rgba in enumerate(self._rgbas):
            rect = Graphene.Rect().init(pad + i * step, pad, max(1, step - gap), h - 2 * pad)
            snapshot.append_color(rgba, rect)


def _build_background_group(page, prefs, app):
    """Board background editor. Returns a function that re-syncs it from prefs."""
    group = Adw.PreferencesGroup()
    group.set_title("Board Background")
    page.add(group)

    reset_button = Gtk.Button(icon_name="edit-undo-symbolic")
    reset_button.add_css_class("flat")
    reset_button.set_valign(Gtk.Align.CENTER)
    reset_button.set_tooltip_text("Reset to Default Background")
    group.set_header_suffix(reset_button)

    gradient_row = Adw.SwitchRow(
        title="Gradient", subtitle="Blend three colors diagonally across the board"
    )
    group.add(gradient_row)

    colors_row = Adw.ActionRow(title="Colors")
    buttons = []
    for tip in ("Top Left", "Middle", "Bottom Right"):
        button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
        button.set_valign(Gtk.Align.CENTER)
        button.set_tooltip_text(tip)
        colors_row.add_suffix(button)
        buttons.append(button)
    group.add(colors_row)

    syncing = False

    def sync_from_prefs():
        nonlocal syncing
        stops = prefs.board_background
        syncing = True
        gradient_row.set_active(len(stops) > 1)
        # Spread 1-3 stops over the three buttons (first, middle, last).
        # A solid colour seeds all three, so turning the gradient on starts flat.
        picks = [stops[0], stops[len(stops) // 2], stops[-1]]
        for button, color in zip(buttons, picks):
            button.set_rgba(_hex_to_rgba(color))
        for button in buttons[1:]:
            button.set_visible(len(stops) > 1)
        colors_row.set_title("Colors" if len(stops) > 1 else "Color")
        syncing = False

    def save_from_controls(*_args):
        if syncing:
            return
        hexes = [_rgba_to_hex(b.get_rgba()) for b in buttons]
        prefs.board_background = hexes if gradient_row.get_active() else hexes[:1]
        for button in buttons[1:]:
            button.set_visible(gradient_row.get_active())
        colors_row.set_title("Colors" if gradient_row.get_active() else "Color")
        prefs.save()
        app.reload_css()

    def on_reset(_button):
        prefs.board_background = list(DEFAULT_BACKGROUND)
        sync_from_prefs()
        prefs.save()
        app.reload_css()

    sync_from_prefs()
    gradient_row.connect("notify::active", save_from_controls)
    for button in buttons:
        button.connect("notify::rgba", save_from_controls)
    reset_button.connect("clicked", on_reset)
    return sync_from_prefs


def _build_colors_page(window, prefs, app, refresh_color_row):
    page = Adw.PreferencesPage(title="Colors", icon_name="applications-graphics-symbolic")

    palette_group = Adw.PreferencesGroup()
    palette_group.set_title("Note Colors")
    palette_group.set_description(
        "Notes remember which slot they use, so editing a color here "
        "recolors every note using it."
    )
    page.add(palette_group)

    add_button = Gtk.Button(icon_name="list-add-symbolic")
    add_button.add_css_class("flat")
    add_button.set_valign(Gtk.Align.CENTER)
    add_button.set_tooltip_text("Add Color")
    palette_group.set_header_suffix(add_button)

    rows = []

    def commit(rebuild):
        prefs.set_palette(prefs.palette)
        prefs.save()
        app.reload_css()
        refresh_color_row()
        if rebuild:
            rebuild_rows()

    def move_slot(index, delta):
        target = index + delta
        if 0 <= target < len(prefs.palette):
            p = prefs.palette
            p[index], p[target] = p[target], p[index]
            commit(True)

    def delete_slot(index):
        if len(prefs.palette) > 1:
            del prefs.palette[index]
            commit(True)

    def make_slot_row(index, slot):
        row = Adw.EntryRow(title="Name")
        row.set_text(slot["name"])

        color_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
        color_button.set_rgba(_hex_to_rgba(slot["color"]))
        color_button.set_valign(Gtk.Align.CENTER)
        color_button.set_tooltip_text("Change Color")
        row.add_prefix(color_button)

        def on_color_set(button, _p):
            prefs.palette[index]["color"] = _rgba_to_hex(button.get_rgba())
            commit(False)

        color_button.connect("notify::rgba", on_color_set)

        def on_name_changed(entry):
            prefs.palette[index]["name"] = entry.get_text().strip() or "Color"
            commit(False)

        row.connect("changed", on_name_changed)

        for icon, tip, cb, sensitive in (
            ("go-up-symbolic", "Move Up", lambda _b: move_slot(index, -1), index > 0),
            (
                "go-down-symbolic",
                "Move Down",
                lambda _b: move_slot(index, 1),
                index < len(prefs.palette) - 1,
            ),
            (
                "user-trash-symbolic",
                "Remove Color",
                lambda _b: delete_slot(index),
                len(prefs.palette) > 1,
            ),
        ):
            button = Gtk.Button(icon_name=icon)
            button.add_css_class("flat")
            button.set_valign(Gtk.Align.CENTER)
            button.set_tooltip_text(tip)
            button.set_sensitive(sensitive)
            button.connect("clicked", cb)
            row.add_suffix(button)
        return row

    def rebuild_rows():
        for row in rows:
            palette_group.remove(row)
        rows.clear()
        for index, slot in enumerate(prefs.palette):
            row = make_slot_row(index, slot)
            palette_group.add(row)
            rows.append(row)

    def on_add(_button):
        last = prefs.palette[-1]["color"] if prefs.palette else "#f9e2af"
        prefs.palette.append(
            {"id": new_slot_id(), "name": f"Color {len(prefs.palette) + 1}", "color": last}
        )
        commit(True)

    add_button.connect("clicked", on_add)
    rebuild_rows()

    refresh_background_controls = _build_background_group(page, prefs, app)

    schemes_group = Adw.PreferencesGroup()
    schemes_group.set_title("Color Schemes")
    schemes_group.set_description(
        "Replace swaps the colors in place (notes keep their slot) and sets the "
        "board background; Add appends the scheme's colors to your palette. "
        "Extra schemes can be dropped into "
        "~/.config/sticky-notes/schemes/ as JSON."
    )
    page.add(schemes_group)

    def load_scheme(scheme, append):
        previous = [dict(s) for s in prefs.palette]
        previous_background = list(prefs.board_background)
        prefs.palette = apply_scheme(prefs.palette, scheme, append=append)
        if not append and scheme.get("background"):
            prefs.board_background = list(scheme["background"])
            refresh_background_controls()
        commit(True)

        toast = Adw.Toast(
            title=f"{'Added' if append else 'Loaded'} “{scheme['name']}”",
            button_label="Undo",
            timeout=5,
        )

        def on_undo(_toast):
            prefs.palette = previous
            prefs.board_background = previous_background
            refresh_background_controls()
            commit(True)

        toast.connect("button-clicked", on_undo)
        window.add_toast(toast)

    for scheme in all_schemes():
        row = Adw.ActionRow(title=scheme["name"])
        row.set_subtitle(f"{len(scheme['colors'])} colors")
        row.add_prefix(
            _SchemePreview(
                [c["color"] for c in scheme["colors"]],
                scheme.get("background", DEFAULT_BACKGROUND),
            )
        )

        append_button = Gtk.Button(icon_name="list-add-symbolic")
        append_button.add_css_class("flat")
        append_button.set_valign(Gtk.Align.CENTER)
        append_button.set_tooltip_text("Add These Colors to Palette")
        append_button.connect("clicked", lambda _b, sc=scheme: load_scheme(sc, True))
        row.add_suffix(append_button)

        replace_button = Gtk.Button(label="Replace")
        replace_button.set_valign(Gtk.Align.CENTER)
        replace_button.set_tooltip_text("Replace Palette with This Scheme")
        replace_button.connect("clicked", lambda _b, sc=scheme: load_scheme(sc, False))
        row.add_suffix(replace_button)

        schemes_group.add(row)

    return page
