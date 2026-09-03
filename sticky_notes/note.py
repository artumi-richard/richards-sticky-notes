import os
import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

URL_RE = re.compile(r"https?://[^\s]+")
PATH_RE = re.compile(r"(?:~|/)[^\s]+")

COLORS = {
    "yellow": "#f9e2af",
    "pink": "#f5c2e7",
    "green": "#a6e3a1",
    "blue": "#89b4fa",
    "orange": "#fab387",
    "purple": "#cba6f7",
    "red": "#f38ba8",
    "teal": "#94e2d5",
    "gray": "#bac2de",
    "lavender": "#b4befe",
}

NOTE_WIDTH = 200
NOTE_HEIGHT = 200
MIN_NOTE_WIDTH = 120
MIN_NOTE_HEIGHT = 100
UNDO_DEBOUNCE_MS = 600
UNDO_STACK_LIMIT = 20

FONT_STYLE_PROPORTIONAL = "proportional"
FONT_STYLE_MONOSPACE = "monospace"

NOTE_CSS = "\n".join(
    f".note-color-{name} {{ background-color: {hex_color}; }}"
    for name, hex_color in COLORS.items()
)


class NoteWidget(Gtk.Overlay):
    """A single draggable, resizable sticky note card living inside a Gtk.Fixed."""

    def __init__(
        self,
        board,
        color_name="yellow",
        text="",
        width=NOTE_WIDTH,
        height=NOTE_HEIGHT,
        font_style=None,
    ):
        super().__init__()
        self.board = board
        self.add_css_class("note-card")
        self.set_size_request(width, height)
        self.is_fullscreen = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        handle = Gtk.CenterBox()
        handle.add_css_class("note-handle")
        handle.set_size_request(-1, 28)
        handle.sticky_note = self
        self.handle = handle

        handle.set_start_widget(self._build_color_menu())

        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        self.undo_button = Gtk.Button(icon_name="edit-undo-symbolic")
        self.undo_button.add_css_class("flat")
        self.undo_button.set_tooltip_text("Undo Last Edit")
        self.undo_button.set_sensitive(False)
        self.undo_button.connect("clicked", self._on_undo_clicked)
        end_box.append(self.undo_button)

        self.redo_button = Gtk.Button(icon_name="edit-redo-symbolic")
        self.redo_button.add_css_class("flat")
        self.redo_button.set_tooltip_text("Redo")
        self.redo_button.set_sensitive(False)
        self.redo_button.connect("clicked", self._on_redo_clicked)
        end_box.append(self.redo_button)

        set_default_size_button = Gtk.Button(icon_name="view-pin-symbolic")
        set_default_size_button.add_css_class("flat")
        set_default_size_button.set_tooltip_text("Set as Default Note Size")
        set_default_size_button.connect("clicked", self._on_set_default_size_clicked)
        end_box.append(set_default_size_button)

        self.font_button = Gtk.Button(icon_name="font-x-generic-symbolic")
        self.font_button.add_css_class("flat")
        self.font_button.set_tooltip_text("Toggle Proportional / Monospace Font")
        self.font_button.connect("clicked", self._on_toggle_font_clicked)
        end_box.append(self.font_button)

        self.fullscreen_button = Gtk.Button(icon_name="view-fullscreen-symbolic")
        self.fullscreen_button.add_css_class("flat")
        self.fullscreen_button.set_tooltip_text("Toggle Fullscreen")
        self.fullscreen_button.connect("clicked", self._on_fullscreen_clicked)
        end_box.append(self.fullscreen_button)

        copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_button.add_css_class("flat")
        copy_button.set_tooltip_text("Copy Text")
        copy_button.connect("clicked", self._on_copy_clicked)
        end_box.append(copy_button)

        close_button = Gtk.Button(icon_name="window-close-symbolic")
        close_button.add_css_class("flat")
        close_button.set_tooltip_text("Delete Note")
        close_button.connect("clicked", self._on_close_clicked)
        end_box.append(close_button)

        handle.set_end_widget(end_box)
        root.append(handle)

        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_top_margin(8)
        self.text_view.set_bottom_margin(8)
        self.text_view.set_left_margin(8)
        self.text_view.set_right_margin(8)
        self.text_view.get_buffer().set_text(text)
        self.text_view.add_css_class("note-text")

        self.link_tag = self.text_view.get_buffer().create_tag(
            "link", foreground="#1e66f5", underline=Pango.Underline.SINGLE
        )

        click = Gtk.GestureClick()
        click.connect("released", self._on_text_click)
        self.text_view.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_text_hover)
        self.text_view.add_controller(motion)

        self._undo_stack = []
        self._redo_stack = []
        self._pending_snapshot = None
        self._undo_debounce_id = None
        self._last_committed_text = text
        self._restoring = False
        self.text_view.get_buffer().connect("changed", self._on_text_changed)

        paste_intercept = Gtk.EventControllerKey()
        paste_intercept.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        paste_intercept.connect("key-pressed", self._on_key_pressed)
        self.text_view.add_controller(paste_intercept)

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("enter", self._on_text_focus_enter)
        focus_ctrl.connect("leave", self._on_text_focus_leave)
        self.text_view.add_controller(focus_ctrl)

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.text_view)
        scroller.set_vexpand(True)
        root.append(scroller)

        self.set_child(root)

        grip = Gtk.Image.new_from_icon_name("view-fullscreen-symbolic")
        grip.set_pixel_size(14)
        grip.add_css_class("note-resize-grip")
        grip.set_halign(Gtk.Align.END)
        grip.set_valign(Gtk.Align.END)
        grip.set_margin_end(2)
        grip.set_margin_bottom(2)
        grip.set_cursor(Gdk.Cursor.new_from_name("nwse-resize"))
        grip.sticky_note_resize = self
        self.add_overlay(grip)

        self._apply_color(color_name)
        self._apply_font_style(font_style or board.prefs.default_font_style)
        self._relink()

    def _build_color_menu(self):
        menu_button = Gtk.MenuButton()
        menu_button.add_css_class("flat")
        menu_button.set_icon_name("applications-graphics-symbolic")
        menu_button.set_tooltip_text("Note Color")

        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for margin in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{margin}")(6)

        for name, hex_color in COLORS.items():
            swatch = Gtk.Button()
            swatch.add_css_class("circular")
            swatch.add_css_class(f"note-color-{name}")
            swatch.set_size_request(24, 24)
            swatch.connect("clicked", self._on_color_selected, name, popover)
            box.append(swatch)

        popover.set_child(box)
        menu_button.set_popover(popover)
        return menu_button

    def _on_color_selected(self, _button, name, popover):
        self._apply_color(name)
        popover.popdown()
        self.board.request_save()

    def _apply_color(self, name):
        for cls in list(self.get_css_classes()):
            if cls.startswith("note-color-"):
                self.remove_css_class(cls)
        self.add_css_class(f"note-color-{name}")
        self.color_name = name

    def _on_close_clicked(self, _button):
        self.board.close_note(self)

    def _on_text_focus_enter(self, _ctrl):
        self.board.set_focused_note(self)
        self.add_css_class("note-focused")

    def _on_text_focus_leave(self, _ctrl):
        self.remove_css_class("note-focused")

    def _on_set_default_size_clicked(self, _button):
        self.board.confirm_set_default_size(self)

    def _apply_font_style(self, style):
        self.text_view.remove_css_class(f"note-font-{FONT_STYLE_PROPORTIONAL}")
        self.text_view.remove_css_class(f"note-font-{FONT_STYLE_MONOSPACE}")
        self.text_view.add_css_class(f"note-font-{style}")
        self.font_style = style

    def _on_toggle_font_clicked(self, _button):
        new_style = (
            FONT_STYLE_MONOSPACE
            if self.font_style == FONT_STYLE_PROPORTIONAL
            else FONT_STYLE_PROPORTIONAL
        )
        self._apply_font_style(new_style)
        self.board.request_save()

    def _on_fullscreen_clicked(self, _button):
        self.board.toggle_note_fullscreen(self)

    def set_fullscreen_state(self, is_fullscreen):
        self.is_fullscreen = is_fullscreen
        self.fullscreen_button.set_icon_name(
            "view-restore-symbolic" if is_fullscreen else "view-fullscreen-symbolic"
        )

    def _on_copy_clicked(self, _button):
        clipboard = self.get_display().get_clipboard()
        clipboard.set(self.get_text())

    def _on_text_changed(self, _buffer):
        if self._restoring:
            return
        self._redo_stack.clear()
        self.redo_button.set_sensitive(False)
        if self._pending_snapshot is None:
            self._pending_snapshot = self._last_committed_text
        if self._undo_debounce_id is not None:
            GLib.source_remove(self._undo_debounce_id)
        self._undo_debounce_id = GLib.timeout_add(UNDO_DEBOUNCE_MS, self._commit_snapshot)
        self.board.request_save()

    def _commit_snapshot(self):
        if self._pending_snapshot is not None:
            self._undo_stack.append(self._pending_snapshot)
            del self._undo_stack[:-UNDO_STACK_LIMIT]
            self._pending_snapshot = None
            self.undo_button.set_sensitive(True)
        self._last_committed_text = self.get_text()
        self._undo_debounce_id = None
        self._relink()
        return False

    def _on_undo_clicked(self, _button):
        if self._undo_debounce_id is not None:
            GLib.source_remove(self._undo_debounce_id)
            self._undo_debounce_id = None
            self._pending_snapshot = None
        if not self._undo_stack:
            return
        current_text = self.get_text()
        previous_text = self._undo_stack.pop()
        self._redo_stack.append(current_text)
        del self._redo_stack[:-UNDO_STACK_LIMIT]
        self._restoring = True
        self.text_view.get_buffer().set_text(previous_text)
        self._restoring = False
        self._last_committed_text = previous_text
        self.undo_button.set_sensitive(bool(self._undo_stack))
        self.redo_button.set_sensitive(True)
        self._relink()
        self.board.request_save()

    def _on_redo_clicked(self, _button):
        if not self._redo_stack:
            return
        current_text = self.get_text()
        next_text = self._redo_stack.pop()
        self._undo_stack.append(current_text)
        del self._undo_stack[:-UNDO_STACK_LIMIT]
        self._restoring = True
        self.text_view.get_buffer().set_text(next_text)
        self._restoring = False
        self._last_committed_text = next_text
        self.redo_button.set_sensitive(bool(self._redo_stack))
        self.undo_button.set_sensitive(True)
        self._relink()
        self.board.request_save()

    def _relink(self):
        buf = self.text_view.get_buffer()
        start, end = buf.get_bounds()
        buf.remove_tag(self.link_tag, start, end)

        text = self.get_text()
        url_spans = []
        for match in URL_RE.finditer(text):
            url = match.group().rstrip(".,;:!?)")
            self._tag_range(buf, match.start(), match.start() + len(url))
            url_spans.append((match.start(), match.start() + len(url)))

        for match in PATH_RE.finditer(text):
            if any(s <= match.start() < e for s, e in url_spans):
                continue  # already tagged as part of a URL
            candidate = match.group().rstrip(".,;:!?)")
            if len(candidate) < 2:
                continue
            expanded = os.path.expanduser(candidate)
            if os.path.isabs(expanded) and os.path.exists(expanded):
                self._tag_range(buf, match.start(), match.start() + len(candidate))

    @staticmethod
    def _tag_range(buf, char_start, char_end):
        it_start = buf.get_iter_at_offset(char_start)
        it_end = buf.get_iter_at_offset(char_end)
        buf.apply_tag_by_name("link", it_start, it_end)

    def _link_at(self, x, y):
        bx, by = self.text_view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self.text_view.get_iter_at_location(bx, by)
        if not found or not it.has_tag(self.link_tag):
            return None
        start = it.copy()
        if not start.starts_tag(self.link_tag):
            start.backward_to_tag_toggle(self.link_tag)
        end = it.copy()
        if not end.ends_tag(self.link_tag):
            end.forward_to_tag_toggle(self.link_tag)
        return self.text_view.get_buffer().get_text(start, end, False)

    def _on_text_click(self, gesture, n_press, x, y):
        if n_press != 1:
            return
        link = self._link_at(x, y)
        if link is None:
            return
        self._open_link(link)

    def _on_text_hover(self, _controller, x, y):
        link = self._link_at(x, y)
        self.text_view.set_cursor(Gdk.Cursor.new_from_name("pointer") if link else None)

    def _open_link(self, link):
        if link.startswith("http://") or link.startswith("https://"):
            uri = link
        else:
            uri = Gio.File.new_for_path(os.path.expanduser(link)).get_uri()
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except Exception:
            pass

    def get_text(self):
        buf = self.text_view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        is_paste = keyval in (Gdk.KEY_v, Gdk.KEY_V) and (
            state & Gdk.ModifierType.CONTROL_MASK
        )
        if not is_paste:
            return False

        clipboard = self.get_display().get_clipboard()
        formats = clipboard.get_formats()
        if not formats.contain_gtype(Gdk.Texture):
            return False  # let normal text paste happen

        clipboard.read_texture_async(None, self._on_texture_ready)
        return True

    def _on_texture_ready(self, clipboard, result):
        try:
            texture = clipboard.read_texture_finish(result)
        except Exception:
            return
        if texture is None:
            return

        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        max_width = max(self.get_width() - 24, 80)
        aspect = texture.get_intrinsic_height() / max(texture.get_intrinsic_width(), 1)
        picture.set_size_request(max_width, int(max_width * aspect))

        buf = self.text_view.get_buffer()
        it = buf.get_iter_at_mark(buf.get_insert())
        anchor = buf.create_child_anchor(it)
        self.text_view.add_child_at_anchor(picture, anchor)
