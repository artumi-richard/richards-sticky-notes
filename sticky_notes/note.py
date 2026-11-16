import base64
import os
import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from . import image_tools
from .christmas import CandyCane, HollySprig
from .colors import DEFAULT_LINK, link_color_for, slot_color, title_color_for

URL_RE = re.compile(r"https?://[^\s]+")
PATH_RE = re.compile(r"(?:~|/)[^\s]+")

NOTE_WIDTH = 200
NOTE_HEIGHT = 200
MIN_NOTE_WIDTH = 120
TAB_WIDTH_SPACES = 2
MIN_NOTE_HEIGHT = 100
UNDO_DEBOUNCE_MS = 600
UNDO_STACK_LIMIT = 20

FONT_STYLE_PROPORTIONAL = "proportional"
FONT_STYLE_MONOSPACE = "monospace"

NOTE_CSS = ".image-viewer { background-color: black; }\n"


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

        # Christmas ornaments sit in the otherwise empty middle of the handle.
        # They ignore input, so dragging by the handle still works over them.
        self.xmas_ornament = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.xmas_ornament.set_can_target(False)
        self.xmas_candy_cane = CandyCane()
        self.xmas_holly = HollySprig()
        self.xmas_ornament.append(self.xmas_candy_cane)
        self.xmas_ornament.append(self.xmas_holly)
        handle.set_center_widget(self.xmas_ornament)

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

        self.xmas_stripe = Gtk.Box()
        self.xmas_stripe.add_css_class("xmas-candy-stripe")
        self.xmas_stripe.set_size_request(-1, 6)
        self.xmas_stripe.set_can_target(False)
        root.append(self.xmas_stripe)

        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_top_margin(8)
        self.text_view.set_bottom_margin(8)
        self.text_view.set_left_margin(8)
        self.text_view.set_right_margin(8)
        self.text_view.get_buffer().set_text(text)
        self.text_view.add_css_class("note-text")

        # Created before the link tag so a link in the title keeps its link colour
        # (later tags take priority).
        self.title_tag = self.text_view.get_buffer().create_tag(
            "xmas-title", weight=Pango.Weight.BOLD
        )
        self.link_tag = self.text_view.get_buffer().create_tag(
            "link", foreground=DEFAULT_LINK, underline=Pango.Underline.SINGLE
        )

        click = Gtk.GestureClick()
        click.connect("released", self._on_text_click)
        self.text_view.add_controller(click)

        # Middle-click pastes the primary selection at the text cursor rather
        # than at the pointer: claim the press in the capture phase so the
        # TextView's own handler never moves the cursor.
        middle_click = Gtk.GestureClick()
        middle_click.set_button(Gdk.BUTTON_MIDDLE)
        middle_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        middle_click.connect("pressed", self._on_middle_click)
        self.text_view.add_controller(middle_click)

        # Selecting text with the left mouse button also copies it to the
        # clipboard. A legacy controller sees the raw release even when the
        # TextView's drag-select gesture has claimed the sequence.
        select_copy = Gtk.EventControllerLegacy()
        select_copy.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        select_copy.connect("event", self._on_text_raw_event)
        self.text_view.add_controller(select_copy)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_text_hover)
        self.text_view.add_controller(motion)

        self._undo_stack = []
        self._redo_stack = []
        self._pending_snapshot = None
        self._undo_debounce_id = None
        # Undo/redo snapshots are content runs (text + images), not plain text.
        self._last_committed = [{"type": "text", "value": text}] if text else []
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
        self.apply_christmas()
        self._relink()

    def _build_color_menu(self):
        menu_button = Gtk.MenuButton()
        menu_button.add_css_class("flat")
        menu_button.set_icon_name("applications-graphics-symbolic")
        menu_button.set_tooltip_text("Note Color")

        popover = Gtk.Popover()
        menu_button.set_popover(popover)
        # Rebuilt on every open so palette edits in Preferences show up.
        popover.connect("show", self._populate_color_popover)
        return menu_button

    def _populate_color_popover(self, popover):
        palette = self.board.prefs.palette
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(True)
        flow.set_max_children_per_line(min(10, max(1, len(palette))))
        flow.set_min_children_per_line(min(5, max(1, len(palette))))
        flow.set_column_spacing(6)
        flow.set_row_spacing(6)
        for margin in ("top", "bottom", "start", "end"):
            getattr(flow, f"set_margin_{margin}")(6)

        for slot in palette:
            swatch = Gtk.Button()
            swatch.add_css_class("circular")
            swatch.add_css_class(f"note-color-{slot['id']}")
            swatch.set_size_request(24, 24)
            swatch.set_tooltip_text(slot["name"])
            if slot["id"] == self.color_name:
                swatch.set_icon_name("object-select-symbolic")
            swatch.connect("clicked", self._on_color_selected, slot["id"], popover)
            child = Gtk.FlowBoxChild(child=swatch, focusable=False)
            flow.append(child)

        popover.set_child(flow)

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
        self.refresh_link_color()

    def apply_christmas(self):
        prefs = self.board.prefs
        on = prefs.christmas_mode
        candy = on and prefs.xmas_candy_cane
        holly = on and prefs.xmas_holly
        self.xmas_candy_cane.set_visible(candy)
        self.xmas_holly.set_visible(holly)
        self.xmas_ornament.set_visible(candy or holly)
        self.xmas_stripe.set_visible(candy)
        self._retitle()

    def _retitle(self):
        """In Christmas mode, show the note's first line as a red title."""
        buf = self.text_view.get_buffer()
        start, end = buf.get_bounds()
        buf.remove_tag(self.title_tag, start, end)
        prefs = self.board.prefs
        if prefs.christmas_mode and prefs.xmas_red_titles:
            line_end = buf.get_start_iter()
            if not line_end.ends_line():
                line_end.forward_to_line_end()
            buf.apply_tag(self.title_tag, start, line_end)

    def refresh_link_color(self):
        """Pick link and title colours readable on this note's current background."""
        background = slot_color(self.board.prefs.palette, self.color_name)
        self.link_tag.set_property("foreground", link_color_for(background))
        self.title_tag.set_property("foreground", title_color_for(background))

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
        # Defer until the new CSS font has been applied to the text view.
        GLib.idle_add(self.update_tab_width)

    def update_tab_width(self):
        """Size tab stops to TAB_WIDTH_SPACES spaces in the current font."""
        layout = self.text_view.create_pango_layout(" " * TAB_WIDTH_SPACES)
        width, _height = layout.get_pixel_size()
        tabs = Pango.TabArray.new(1, True)
        tabs.set_tab(0, Pango.TabAlign.LEFT, max(width, 1))
        self.text_view.set_tabs(tabs)
        return GLib.SOURCE_REMOVE

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
            self._pending_snapshot = self._last_committed
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
        self._last_committed = self.get_content_runs()
        self._undo_debounce_id = None
        self._relink()
        return False

    def _on_undo_clicked(self, _button):
        if self._undo_debounce_id is not None:
            # Flush the in-flight edit so it is the one being undone.
            GLib.source_remove(self._undo_debounce_id)
            self._commit_snapshot()
        if not self._undo_stack:
            return
        current = self.get_content_runs()
        previous = self._undo_stack.pop()
        self._redo_stack.append(current)
        del self._redo_stack[:-UNDO_STACK_LIMIT]
        self.set_content_runs(previous)
        self.undo_button.set_sensitive(bool(self._undo_stack))
        self.redo_button.set_sensitive(True)
        self.board.request_save()

    def _on_redo_clicked(self, _button):
        if not self._redo_stack:
            return
        current = self.get_content_runs()
        following = self._redo_stack.pop()
        self._undo_stack.append(current)
        del self._undo_stack[:-UNDO_STACK_LIMIT]
        self.set_content_runs(following)
        self.redo_button.set_sensitive(bool(self._redo_stack))
        self.undo_button.set_sensitive(True)
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

        self._retitle()

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

    def get_cursor_offset(self):
        buf = self.text_view.get_buffer()
        return buf.get_iter_at_mark(buf.get_insert()).get_offset()

    def set_cursor_offset(self, offset):
        buf = self.text_view.get_buffer()
        end_offset = buf.get_end_iter().get_offset()
        offset = max(0, min(offset, end_offset))
        buf.place_cursor(buf.get_iter_at_offset(offset))

    def _on_text_raw_event(self, _controller, event):
        if (
            event.get_event_type() == Gdk.EventType.BUTTON_RELEASE
            and event.get_button() == Gdk.BUTTON_PRIMARY
        ):
            # Defer until the TextView has finished updating the selection.
            GLib.idle_add(self._copy_selection_to_clipboard)
        return False

    def _copy_selection_to_clipboard(self):
        buf = self.text_view.get_buffer()
        if buf.get_has_selection():
            buf.copy_clipboard(self.get_display().get_clipboard())
        return GLib.SOURCE_REMOVE

    def _on_middle_click(self, gesture, _n_press, _x, _y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.text_view.grab_focus()
        self.get_display().get_primary_clipboard().read_text_async(
            None, self._on_primary_text_ready
        )

    def _on_primary_text_ready(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except Exception:
            return
        if not text:
            return
        buf = self.text_view.get_buffer()
        buf.insert_interactive_at_cursor(text, -1, self.text_view.get_editable())
        self.text_view.scroll_mark_onscreen(buf.get_insert())

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

        buf = self.text_view.get_buffer()
        it = buf.get_iter_at_mark(buf.get_insert())
        image_bytes = bytes(texture.save_to_png_bytes().get_data())
        self._insert_image_at_iter(it, texture, image_bytes)
        self.board.request_save()

    def _insert_image_at_iter(self, it, texture, image_bytes):
        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        req_w, _req_h = self.get_size_request()
        available_w = req_w if req_w > 0 else (self.get_width() or 300)
        max_width = max(available_w - 24, 80)
        aspect = texture.get_intrinsic_height() / max(texture.get_intrinsic_width(), 1)
        picture.set_size_request(max_width, int(max_width * aspect))
        picture.set_cursor(Gdk.Cursor.new_from_name("pointer"))

        buf = self.text_view.get_buffer()
        anchor = buf.create_child_anchor(it)
        anchor.image_bytes = image_bytes

        # Any button (left or right) opens the image menu. Act on press and
        # claim it so the text view's own right-click menu doesn't also open.
        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("pressed", self._on_image_clicked, picture, texture, anchor)
        picture.add_controller(click)

        self.text_view.add_child_at_anchor(picture, anchor)

    def _on_image_clicked(self, gesture, _n_press, x, y, picture, texture, anchor):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        popover = Gtk.Popover()
        popover.set_has_arrow(True)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)

        root = self.get_root()
        items = [
            ("View Full Screen", "view-fullscreen-symbolic",
             lambda: self._show_image_fullscreen(texture)),
            None,
            ("Copy Image", "edit-copy-symbolic", lambda: self._copy_image(texture)),
            ("Resize & Copy…", "edit-copy-symbolic",
             lambda: image_tools.show_resize_dialog(root, texture, "Copy", self._copy_image)),
            None,
            ("Save Image…", "document-save-symbolic",
             lambda: image_tools.save_texture(root, texture, self._show_image_error)),
            ("Resize & Save…", "document-save-as-symbolic",
             lambda: image_tools.show_resize_dialog(
                 root, texture, "Save…",
                 lambda t: image_tools.save_texture(root, t, self._show_image_error))),
        ]
        if image_tools.find_gimp():
            items.append(("Open in GIMP", "applications-graphics-symbolic",
                          lambda: self._open_in_gimp(texture)))
        items += [
            None,
            ("Delete Image", "user-trash-symbolic", lambda: self._delete_image(anchor)),
        ]

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for item in items:
            if item is None:
                box.append(Gtk.Separator())
                continue
            label, icon, action = item
            content = Adw.ButtonContent(label=label, icon_name=icon, use_underline=False)
            content.set_halign(Gtk.Align.START)
            button = Gtk.Button(child=content)
            button.add_css_class("flat")
            button.connect("clicked", self._on_image_action, popover, action)
            box.append(button)
        popover.set_child(box)

        popover.set_parent(picture)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()

    def _on_image_action(self, _button, popover, action):
        popover.popdown()
        # Defer so the popover (parented to the picture) is closed before the
        # action runs; deleting the image destroys the picture.
        GLib.idle_add(lambda: action() and False)

    def _open_in_gimp(self, texture):
        error = image_tools.open_in_gimp(texture)
        if error:
            self._show_image_error(error)

    def _show_image_error(self, message):
        dialog = Adw.AlertDialog(heading="Image Error", body=message)
        dialog.add_response("ok", "OK")
        dialog.present(self.get_root())

    def _delete_image(self, anchor):
        if anchor.get_deleted():
            return
        buf = self.text_view.get_buffer()
        start = buf.get_iter_at_child_anchor(anchor)
        end = start.copy()
        end.forward_char()
        buf.delete(start, end)
        self.board.request_save()

    def _copy_image(self, texture):
        # Declare the value as Gdk.Texture (not the concrete subclass, e.g.
        # GdkMemoryTexture) so paste's contain_gtype(Gdk.Texture) matches.
        value = GObject.Value(Gdk.Texture, texture)
        provider = Gdk.ContentProvider.new_for_value(value)
        self.get_display().get_clipboard().set_content(provider)

    def _show_image_fullscreen(self, texture):
        window = Gtk.Window()
        window.set_title("Image")
        window.add_css_class("image-viewer")
        root = self.get_root()
        if isinstance(root, Gtk.Window):
            window.set_transient_for(root)
            window.set_modal(True)

        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
        window.set_child(picture)

        def on_key(_ctrl, keyval, _keycode, _state):
            if keyval == Gdk.KEY_Escape:
                window.close()
                return True
            return False

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", on_key)
        window.add_controller(keys)

        click = Gtk.GestureClick()
        click.connect("released", lambda *_: window.close())
        window.add_controller(click)

        window.fullscreen()
        window.present()

    def get_content_runs(self):
        """Serialize text + embedded images, in order, for persistence."""
        buf = self.text_view.get_buffer()
        runs = []
        it = buf.get_start_iter()
        chunk_start = it.copy()
        while True:
            anchor = it.get_child_anchor()
            if anchor is not None:
                if not it.equal(chunk_start):
                    runs.append({"type": "text", "value": buf.get_text(chunk_start, it, False)})
                image_bytes = getattr(anchor, "image_bytes", None)
                if image_bytes:
                    runs.append(
                        {"type": "image", "data": base64.b64encode(image_bytes).decode("ascii")}
                    )
                if not it.forward_char():
                    break
                chunk_start = it.copy()
                continue
            if not it.forward_char():
                break

        end = buf.get_end_iter()
        if not chunk_start.equal(end):
            runs.append({"type": "text", "value": buf.get_text(chunk_start, end, False)})
        return runs

    def set_content_runs(self, runs):
        """Rebuild text + embedded images from get_content_runs() output."""
        buf = self.text_view.get_buffer()
        self._restoring = True
        buf.set_text("")
        for run in runs:
            if run.get("type") == "text":
                buf.insert(buf.get_end_iter(), run.get("value", ""))
            elif run.get("type") == "image":
                try:
                    image_bytes = base64.b64decode(run["data"])
                    texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(image_bytes))
                except (GLib.Error, ValueError, KeyError):
                    continue
                self._insert_image_at_iter(buf.get_end_iter(), texture, image_bytes)
        self._restoring = False
        self._last_committed = self.get_content_runs()
        self._relink()
