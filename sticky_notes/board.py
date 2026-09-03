import json
import os
import time
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from .note import MIN_NOTE_HEIGHT, MIN_NOTE_WIDTH, NoteWidget
from .prefs import (
    FULLSCREEN_MODE_SCREEN,
    ON_CLOSE_REFLOW_GRID,
    PLACEMENT_CASCADE,
    PLACEMENT_FREE_SPACE,
)
from .prefs_ui import build_preferences_window

CLOSED_RETENTION_SECONDS = 60 * 24 * 60 * 60  # 60 days
SAVE_DEBOUNCE_MS = 800

STATE_DIR = Path(GLib.get_user_data_dir()) / "sticky-notes"
STATE_FILE = STATE_DIR / "notes.json"


class BoardWindow(Adw.ApplicationWindow):
    """The single top-level window that hosts every sticky note."""

    def __init__(self, prefs, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(900, 650)
        self.set_title("Sticky Notes")

        self.prefs = prefs

        self._positions = {}
        self._sizes = {}
        self._next_cascade = 0
        self._closed_notes = []  # list of dicts: color, text, position, size, closed_at
        self._drag_mode = None  # "move" or "resize"
        self._drag_note = None
        self._drag_origin = (0, 0)
        self._save_pending_id = None
        self._focused_note = None
        self._fullscreen_note = None
        self._fullscreen_saved = None

        self.connect("close-request", self._on_close_request)

        self._used_os_fullscreen = False

        self._create_action("new-note", lambda *_a: self.add_note())
        self._create_action("close-focused-note", lambda *_a: self.close_focused_note())
        self._create_action("focus-next-note", lambda *_a: self.focus_relative_note(1))
        self._create_action("focus-prev-note", lambda *_a: self.focus_relative_note(-1))
        self._create_action(
            "toggle-fullscreen-note", lambda *_a: self.toggle_fullscreen_focused_note()
        )
        self._create_action("show-shortcuts", lambda *_a: self._show_shortcuts_window())

        toolbar_view = Adw.ToolbarView()

        header = Adw.HeaderBar()

        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.set_tooltip_text("New Note")
        add_button.connect("clicked", lambda _b: self.add_note())
        header.pack_start(add_button)

        self.cascade_button = Gtk.Button(icon_name="view-continuous-symbolic")
        self.cascade_button.connect("clicked", lambda _b: self.sort_cascade())
        header.pack_start(self.cascade_button)
        self.set_cascade_enabled(not prefs.prevent_overlap)

        grid_button = Gtk.Button(icon_name="view-grid-symbolic")
        grid_button.set_tooltip_text("Arrange in Grid")
        grid_button.connect("clicked", lambda _b: self.sort_grid())
        header.pack_start(grid_button)

        self.closed_button = Gtk.Button(icon_name="edit-undo-symbolic")
        self.closed_button.set_tooltip_text("Recently Closed")
        self.closed_button.connect("clicked", self._on_closed_clicked)
        header.pack_start(self.closed_button)

        self.closed_window = Adw.Window()
        self.closed_window.set_title("Recently Closed Notes")
        self.closed_window.set_default_size(380, 520)
        self.closed_window.set_hide_on_close(True)
        closed_toolbar = Adw.ToolbarView()
        closed_toolbar.add_top_bar(Adw.HeaderBar())
        self.closed_scroller = Gtk.ScrolledWindow()
        self.closed_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        closed_toolbar.set_content(self.closed_scroller)
        self.closed_window.set_content(closed_toolbar)

        prefs_button = Gtk.Button(icon_name="preferences-system-symbolic")
        prefs_button.set_tooltip_text("Preferences")
        prefs_button.connect("clicked", self._on_prefs_clicked)
        header.pack_end(prefs_button)

        shortcuts_button = Gtk.Button(icon_name="preferences-desktop-keyboard-shortcuts-symbolic")
        shortcuts_button.set_tooltip_text("Keyboard Shortcuts")
        shortcuts_button.connect("clicked", lambda _b: self._show_shortcuts_window())
        header.pack_end(shortcuts_button)

        toolbar_view.add_top_bar(header)

        self.fixed = Gtk.Fixed()
        self.fixed.add_css_class("board-background")
        self.fixed.set_hexpand(True)
        self.fixed.set_vexpand(True)
        self.fixed.set_size_request(900, 650)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.fixed.add_controller(drag)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_overlay_scrolling(False)
        self.scroller.set_child(self.fixed)

        toolbar_view.set_content(self.scroller)
        self.set_content(toolbar_view)

        self._refresh_closed_menu()

    def add_note(self, color_name=None, text="", position=None, size=None, font_style=None):
        if color_name is None:
            color_name = self.prefs.pick_color()
        if size is None:
            size = self.prefs.default_size()
        width, height = size

        note = NoteWidget(
            self,
            color_name=color_name,
            text=text,
            width=width,
            height=height,
            font_style=font_style,
        )
        if position is None:
            position = self._pick_placement(size)
        x, y = position

        self.fixed.put(note, x, y)
        self._positions[note] = (x, y)
        self._sizes[note] = (width, height)
        self._recompute_canvas_size()
        self.request_save()
        return note

    def close_note(self, note):
        if note is self._fullscreen_note:
            for other in self._positions:
                if other is not note:
                    other.set_visible(True)
            self._fullscreen_note = None
            self._fullscreen_saved = None

        x, y = self._positions.get(note, (0, 0))
        w, h = self._sizes.get(note, (0, 0))
        self._closed_notes.append(
            {
                "color": note.color_name,
                "text": note.get_text(),
                "content": note.get_content_runs(),
                "position": (x, y),
                "size": (w, h),
                "font_style": note.font_style,
                "closed_at": time.time(),
            }
        )
        if note is self._focused_note:
            self._focused_note = None
        self.fixed.remove(note)
        self._positions.pop(note, None)
        self._sizes.pop(note, None)
        self._recompute_canvas_size()
        self._purge_expired_closed()
        self._refresh_closed_menu()
        if self.prefs.on_close_action == ON_CLOSE_REFLOW_GRID:
            self.sort_grid()
        self.request_save()

    def restore_note(self, entry):
        self._closed_notes.remove(entry)
        size = entry["size"] if entry["size"][0] and entry["size"][1] else self.prefs.default_size()
        x, y = entry["position"]
        w, h = size
        if self._would_overlap(None, x, y, w, h):
            x, y = self._find_free_space(size)
        note = self.add_note(
            color_name=entry["color"],
            text=entry["text"],
            position=(x, y),
            size=size,
            font_style=entry.get("font_style"),
        )
        if entry.get("content"):
            note.set_content_runs(entry["content"])
        self._refresh_closed_menu()
        self.request_save()

    def get_note_position(self, note):
        return self._positions.get(note, (0, 0))

    def get_note_size(self, note):
        return self._sizes.get(note, (MIN_NOTE_WIDTH, MIN_NOTE_HEIGHT))

    def _snap_position(self, value):
        spacing = self.prefs.grid_spacing
        if spacing <= 0:
            return value
        margin = self.prefs.grid_margin
        cell = round((value - margin) / spacing)
        return cell * spacing + margin

    def _snap_size(self, value, minimum):
        spacing = self.prefs.grid_spacing
        if spacing <= 0:
            return max(value, minimum)
        margin = self.prefs.grid_margin
        cells = max(1, round((value + 2 * margin) / spacing))
        return max(minimum, cells * spacing - 2 * margin)

    def move_note(self, note, x, y):
        x = max(0.0, self._snap_position(x))
        y = max(0.0, self._snap_position(y))
        self.fixed.move(note, x, y)
        self._positions[note] = (x, y)
        self._recompute_canvas_size()
        self.request_save()

    def resize_note(self, note, w, h):
        w = self._snap_size(w, MIN_NOTE_WIDTH)
        h = self._snap_size(h, MIN_NOTE_HEIGHT)
        note.set_size_request(w, h)
        self._sizes[note] = (w, h)
        self._recompute_canvas_size()
        self.request_save()

    def _recompute_canvas_size(self):
        max_x = 0
        max_y = 0
        for note, (x, y) in self._positions.items():
            w, h = self._sizes.get(note, (0, 0))
            max_x = max(max_x, x + w)
            max_y = max(max_y, y + h)
        margin = self.prefs.grid_margin
        new_w = int(max_x + margin) if self._positions else 0
        new_h = int(max_y + margin) if self._positions else 0
        self.fixed.set_size_request(new_w, new_h)

    def raise_note(self, note):
        # Reorder within the same parent (no unparent/reparent) so focus and
        # in-progress click/gesture routing to the note's children survive.
        note.insert_before(self.fixed, None)

    def _reading_order(self):
        """Notes top-to-bottom, left-to-right by current on-screen position
        (like window-manager icon layout), not creation order."""
        items = [
            (note, x, y, self._sizes.get(note, (0, 0))[1])
            for note, (x, y) in self._positions.items()
        ]
        items.sort(key=lambda item: item[2])  # by y

        rows = []
        for note, x, y, h in items:
            for row in rows:
                if abs(y - row["y"]) <= row["h"] / 2:
                    row["items"].append((note, x))
                    row["y"] = min(row["y"], y)
                    row["h"] = max(row["h"], h)
                    break
            else:
                rows.append({"y": y, "h": h, "items": [(note, x)]})

        ordered = []
        for row in rows:
            ordered.extend(note for note, _x in sorted(row["items"], key=lambda t: t[1]))
        return ordered

    def sort_cascade(self):
        self._next_cascade = 0
        for note in self._reading_order():
            x, y = self._next_position()
            self.fixed.move(note, x, y)
            self._positions[note] = (x, y)
        self._recompute_canvas_size()
        self.request_save()

    def sort_grid(self):
        margin = self.prefs.grid_margin
        viewport_w = self.scroller.get_width() or self.fixed.get_width() or 900
        x = margin
        y = margin
        row_height = 0
        for note in self._reading_order():
            w, h = self._sizes.get(note, self.prefs.default_size())
            if x > margin and x + w > viewport_w:
                x = margin
                y += row_height + margin
                row_height = 0
            self.fixed.move(note, x, y)
            self._positions[note] = (x, y)
            row_height = max(row_height, h)
            x += w + margin
        self._recompute_canvas_size()
        self.request_save()

    def _would_overlap(self, note, x, y, w, h):
        candidate = (x, y, x + w, y + h)
        for other, (ox, oy) in self._positions.items():
            if other is note:
                continue
            ow, oh = self._sizes.get(other, (0, 0))
            if self._rects_overlap(candidate, (ox, oy, ox + ow, oy + oh)):
                return True
        return False

    def _pick_placement(self, size):
        if self.prefs.placement_mode == PLACEMENT_FREE_SPACE:
            return self._find_free_space(size)
        return self._next_position()

    def _next_position(self):
        margin = self.prefs.grid_margin
        offset = self._next_cascade * self.prefs.grid_spacing
        self._next_cascade = (self._next_cascade + 1) % 10
        return margin + offset, margin + offset

    def _find_free_space(self, size):
        width, height = size
        margin = self.prefs.grid_margin

        viewport_w = self.scroller.get_width() or self.fixed.get_width() or 900
        max_x = max(margin, int(viewport_w - width))

        occupied = [
            (px, py, px + self._sizes.get(note, (0, 0))[0], py + self._sizes.get(note, (0, 0))[1])
            for note, (px, py) in self._positions.items()
        ]

        # Candidate positions are derived from the actual edges of existing
        # notes (not a fixed-size grid raster), so a new note packs exactly
        # `margin` px from its neighbors — matching sort_grid's tight
        # shelf-packing instead of landing up to a whole grid_spacing
        # further away than necessary.
        candidate_xs = sorted({margin} | {rect[2] + margin for rect in occupied})
        candidate_ys = sorted({margin} | {rect[3] + margin for rect in occupied})

        for y in candidate_ys:
            for x in candidate_xs:
                if x > max_x:
                    continue
                # Pad the check by margin so the found spot keeps at least
                # a margin's gap from neighbors, not just zero overlap
                # (rect overlap is a strict inequality, so touching edges
                # would otherwise count as "free").
                padded = (x - margin, y - margin, x + width + margin, y + height + margin)
                if not any(self._rects_overlap(padded, rect) for rect in occupied):
                    return (x, y)

        return self._next_position()

    @staticmethod
    def _rects_overlap(a, b):
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0

    def _purge_expired_closed(self):
        cutoff = time.time() - CLOSED_RETENTION_SECONDS
        self._closed_notes = [
            entry for entry in self._closed_notes if entry["closed_at"] >= cutoff
        ]

    @staticmethod
    def _closed_entry_snippet(entry):
        stripped = entry.get("text", "").strip()
        if stripped:
            snippet = stripped.splitlines()[0]
        elif any(run.get("type") == "image" for run in entry.get("content") or []):
            snippet = "Image"
        else:
            snippet = "(empty note)"
        if len(snippet) > 28:
            snippet = snippet[:28] + "…"
        return snippet

    @staticmethod
    def _day_heading(day):
        today = date_cls.today()
        if day == today:
            return "Today"
        if day == today - timedelta(days=1):
            return "Yesterday"
        return day.strftime("%A, %d %B")

    def _refresh_closed_menu(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for margin in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{margin}")(8)
        box.set_size_request(320, -1)

        if not self._closed_notes:
            label = Gtk.Label(label="No recently closed notes")
            label.add_css_class("dim-label")
            box.append(label)
        else:
            current_day = None
            for entry in reversed(self._closed_notes):
                closed_dt = datetime.fromtimestamp(entry["closed_at"])
                if closed_dt.date() != current_day:
                    current_day = closed_dt.date()
                    heading = Gtk.Label(label=self._day_heading(current_day), xalign=0)
                    heading.add_css_class("heading")
                    heading.set_margin_top(8)
                    box.append(heading)

                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

                swatch = Gtk.Box()
                swatch.add_css_class(f"note-color-{entry['color']}")
                swatch.add_css_class("closed-swatch")
                swatch.set_size_request(14, 14)
                row.append(swatch)

                label = Gtk.Label(label=self._closed_entry_snippet(entry), xalign=0)
                label.set_hexpand(True)
                row.append(label)

                time_label = Gtk.Label(label=closed_dt.strftime("%H:%M"))
                time_label.add_css_class("dim-label")
                row.append(time_label)

                restore_button = Gtk.Button(icon_name="edit-undo-symbolic")
                restore_button.add_css_class("flat")
                restore_button.set_tooltip_text("Restore")
                restore_button.connect("clicked", self._on_restore_clicked, entry)
                row.append(restore_button)

                delete_button = Gtk.Button(icon_name="user-trash-symbolic")
                delete_button.add_css_class("flat")
                delete_button.set_tooltip_text("Delete Permanently")
                delete_button.connect("clicked", self._on_delete_closed_clicked, entry)
                row.append(delete_button)

                box.append(row)

        self.closed_scroller.set_child(box)
        self.closed_button.set_sensitive(True)

    def _on_closed_clicked(self, _button):
        self.closed_window.set_transient_for(self)
        self.closed_window.present()

    def _on_restore_clicked(self, _button, entry):
        self.restore_note(entry)

    def _on_delete_closed_clicked(self, _button, entry):
        if entry in self._closed_notes:
            self._closed_notes.remove(entry)
        self._refresh_closed_menu()
        self.request_save()

    def confirm_set_default_size(self, note):
        w, h = self._sizes.get(note, (0, 0))
        dialog = Adw.MessageDialog.new(
            self,
            "Set Default Note Size?",
            f"New notes will be created at {int(w)} × {int(h)} pixels, "
            "matching this note's current size.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("continue", "Set as Default")
        dialog.set_response_appearance("continue", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_set_default_size_response, int(w), int(h))
        dialog.present()

    def _on_set_default_size_response(self, _dialog, response, w, h):
        if response == "continue":
            self.prefs.default_width = w
            self.prefs.default_height = h
            self.prefs.save()

    def set_cascade_enabled(self, enabled):
        self.cascade_button.set_sensitive(enabled)
        self.cascade_button.set_tooltip_text(
            "Arrange in Cascade"
            if enabled
            else "Cascade overlaps notes by design — disabled while "
            "“Prevent Notes Overlapping” is on"
        )

    def _on_prefs_clicked(self, _button):
        window = build_preferences_window(self.prefs, self.get_application(), self)
        window.set_transient_for(self)
        window.present()

    def _create_action(self, name, callback):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda action, param: callback())
        self.add_action(action)

    def set_focused_note(self, note):
        self._focused_note = note

    def close_focused_note(self):
        if self._focused_note is not None:
            self.close_note(self._focused_note)

    def focus_relative_note(self, direction):
        order = list(self._positions.keys())
        if not order:
            return
        if self._focused_note in order:
            idx = order.index(self._focused_note)
        else:
            idx = -1 if direction > 0 else 0
        target = order[(idx + direction) % len(order)]
        self.raise_note(target)
        target.text_view.grab_focus()
        self._focused_note = target

    def toggle_fullscreen_focused_note(self):
        if self._fullscreen_note is not None:
            self.toggle_note_fullscreen(self._fullscreen_note)
        elif self._focused_note is not None:
            self.toggle_note_fullscreen(self._focused_note)

    def _show_shortcuts_window(self):
        builder_xml = """
        <interface>
          <object class="GtkShortcutsWindow" id="shortcuts">
            <property name="modal">1</property>
            <child>
              <object class="GtkShortcutsSection">
                <property name="visible">1</property>
                <child>
                  <object class="GtkShortcutsGroup">
                    <property name="title" translatable="yes">Notes</property>
                    <child>
                      <object class="GtkShortcutsShortcut">
                        <property name="title" translatable="yes">New note</property>
                        <property name="accelerator">&lt;Control&gt;n</property>
                      </object>
                    </child>
                    <child>
                      <object class="GtkShortcutsShortcut">
                        <property name="title" translatable="yes">Close focused note</property>
                        <property name="accelerator">&lt;Control&gt;q</property>
                      </object>
                    </child>
                    <child>
                      <object class="GtkShortcutsShortcut">
                        <property name="title" translatable="yes">Focus next note</property>
                        <property name="accelerator">&lt;Control&gt;Page_Down</property>
                      </object>
                    </child>
                    <child>
                      <object class="GtkShortcutsShortcut">
                        <property name="title" translatable="yes">Focus previous note</property>
                        <property name="accelerator">&lt;Control&gt;Page_Up</property>
                      </object>
                    </child>
                    <child>
                      <object class="GtkShortcutsShortcut">
                        <property name="title" translatable="yes">Toggle fullscreen note</property>
                        <property name="accelerator">F11</property>
                      </object>
                    </child>
                    <child>
                      <object class="GtkShortcutsShortcut">
                        <property name="title" translatable="yes">Show this help</property>
                        <property name="accelerator">&lt;Control&gt;question</property>
                      </object>
                    </child>
                  </object>
                </child>
              </object>
            </child>
          </object>
        </interface>
        """
        builder = Gtk.Builder.new_from_string(builder_xml, -1)
        window = builder.get_object("shortcuts")
        window.set_transient_for(self)
        window.present()

    def toggle_note_fullscreen(self, note):
        if self._fullscreen_note is note:
            self._exit_note_fullscreen()
            return
        if self._fullscreen_note is not None:
            self._exit_note_fullscreen()
        self._enter_note_fullscreen(note)

    def _enter_note_fullscreen(self, note):
        self._fullscreen_note = note
        self._fullscreen_saved = (
            self._positions.get(note, (0, 0)),
            self._sizes.get(note, (0, 0)),
        )
        for other in self._positions:
            if other is not note:
                other.set_visible(False)

        self.raise_note(note)

        if self.prefs.fullscreen_mode == FULLSCREEN_MODE_SCREEN:
            self._used_os_fullscreen = True
            self.fullscreen()
            screen_w, screen_h = self._current_monitor_size()
            target_w = min(int(screen_w * 0.6), 900)
            target_h = screen_h
            x = max(0, (screen_w - target_w) // 2)
            y = 0
            self.move_note(note, x, y)
            self.resize_note(note, target_w, target_h)
        else:
            viewport_w = self.scroller.get_width() or self.fixed.get_width() or 900
            viewport_h = self.scroller.get_height() or self.fixed.get_height() or 650
            self.move_note(note, 0, 0)
            self.resize_note(note, viewport_w, viewport_h)

        note.set_fullscreen_state(True)

    def _current_monitor_size(self):
        display = self.get_display()
        surface = self.get_surface()
        monitor = display.get_monitor_at_surface(surface) if surface else None
        if monitor is None:
            monitors = display.get_monitors()
            monitor = monitors.get_item(0) if monitors.get_n_items() else None
        if monitor is None:
            return 1920, 1080
        geo = monitor.get_geometry()
        return geo.width, geo.height

    def _exit_note_fullscreen(self):
        note = self._fullscreen_note
        if note is None:
            return
        (x, y), (w, h) = self._fullscreen_saved
        for other in self._positions:
            other.set_visible(True)
        if self._used_os_fullscreen:
            self.unfullscreen()
            self._used_os_fullscreen = False
        self.move_note(note, x, y)
        self.resize_note(note, w, h)
        note.set_fullscreen_state(False)
        self._fullscreen_note = None
        self._fullscreen_saved = None

    def _on_drag_begin(self, _gesture, start_x, start_y):
        picked = self.fixed.pick(start_x, start_y, Gtk.PickFlags.DEFAULT)

        clicked_note = picked
        while clicked_note is not None and not isinstance(clicked_note, NoteWidget):
            clicked_note = clicked_note.get_parent()
        if clicked_note is not None:
            self.raise_note(clicked_note)

        resize_note = getattr(picked, "sticky_note_resize", None)
        if resize_note is not None:
            self._drag_mode = "resize"
            self._drag_note = resize_note
            self._drag_origin = self.get_note_size(resize_note)
            return

        move_note = getattr(picked, "sticky_note", None)
        if move_note is not None:
            self._drag_mode = "move"
            self._drag_note = move_note
            self._drag_origin = self.get_note_position(move_note)
            return

        self._drag_mode = None
        self._drag_note = None

    def _on_drag_update(self, _gesture, offset_x, offset_y):
        if self._drag_note is None:
            return
        if self._drag_mode == "move":
            origin_x, origin_y = self._drag_origin
            new_x = max(0.0, origin_x + offset_x)
            new_y = max(0.0, origin_y + offset_y)
            self.move_note(self._drag_note, new_x, new_y)
        elif self._drag_mode == "resize":
            origin_w, origin_h = self._drag_origin
            new_w = max(MIN_NOTE_WIDTH, origin_w + offset_x)
            new_h = max(MIN_NOTE_HEIGHT, origin_h + offset_y)
            self.resize_note(self._drag_note, new_w, new_h)

    def _on_drag_end(self, _gesture, _offset_x, _offset_y):
        note = self._drag_note
        mode = self._drag_mode
        self._drag_mode = None
        self._drag_note = None
        if note is not None and mode in ("move", "resize") and self.prefs.prevent_overlap:
            self._snap_out_of_overlap(note)

    def _snap_out_of_overlap(self, note, max_radius=300):
        w, h = self._sizes.get(note, (0, 0))
        x, y = self._positions.get(note, (0, 0))
        if not self._would_overlap(note, x, y, w, h):
            return

        # Search outward in grid-spacing steps (not steps sized to this note)
        # so the snap lands in the closest actual gap, not a note-sized jump.
        step = max(1, self.prefs.grid_spacing)
        col = round(x / step)
        row = round(y / step)

        for radius in range(max_radius + 1):
            for dc in range(-radius, radius + 1):
                for dr in range(-radius, radius + 1):
                    if max(abs(dc), abs(dr)) != radius:
                        continue
                    cx = max(0, (col + dc) * step)
                    cy = max(0, (row + dr) * step)
                    if not self._would_overlap(note, cx, cy, w, h):
                        self.move_note(note, cx, cy)
                        return

    # -- persistence -----------------------------------------------------

    def request_save(self):
        if self._save_pending_id is not None:
            return
        self._save_pending_id = GLib.timeout_add(SAVE_DEBOUNCE_MS, self._do_save)

    def _do_save(self):
        self._save_pending_id = None
        self._write_state()
        return False

    def _on_close_request(self, *_args):
        if self._save_pending_id is not None:
            GLib.source_remove(self._save_pending_id)
            self._save_pending_id = None
        self._write_state()
        return False

    def _write_state(self):
        notes_data = []
        for note, (x, y) in self._positions.items():
            w, h = self._sizes.get(note, self.prefs.default_size())
            notes_data.append(
                {
                    "text": note.get_text(),
                    "content": note.get_content_runs(),
                    "color": note.color_name,
                    "font_style": note.font_style,
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                }
            )

        closed_data = [
            {
                "text": entry["text"],
                "content": entry.get("content"),
                "color": entry["color"],
                "font_style": entry.get("font_style"),
                "x": entry["position"][0],
                "y": entry["position"][1],
                "w": entry["size"][0],
                "h": entry["size"][1],
                "closed_at": entry["closed_at"],
            }
            for entry in self._closed_notes
        ]

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"notes": notes_data, "closed_notes": closed_data}, indent=2)
        tmp_file = STATE_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(payload)
        os.replace(tmp_file, STATE_FILE)

    def load_state(self):
        """Load saved notes/closed-notes. Returns True if a state file existed."""
        try:
            data = json.loads(STATE_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return False

        for entry in data.get("notes", []):
            note = self.add_note(
                color_name=entry.get("color", "yellow"),
                text=entry.get("text", ""),
                position=(entry.get("x", 24), entry.get("y", 24)),
                size=(
                    entry.get("w", self.prefs.default_width),
                    entry.get("h", self.prefs.default_height),
                ),
                font_style=entry.get("font_style"),
            )
            if entry.get("content"):
                note.set_content_runs(entry["content"])

        for entry in data.get("closed_notes", []):
            self._closed_notes.append(
                {
                    "color": entry.get("color", "yellow"),
                    "text": entry.get("text", ""),
                    "content": entry.get("content"),
                    "position": (entry.get("x", 0), entry.get("y", 0)),
                    "size": (entry.get("w", 0), entry.get("h", 0)),
                    "font_style": entry.get("font_style"),
                    "closed_at": entry.get("closed_at", time.time()),
                }
            )
        self._purge_expired_closed()
        self._refresh_closed_menu()
        return True
