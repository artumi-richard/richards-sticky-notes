"""Image helpers for note images: resize dialog, save-to-file, open in GIMP."""

import os
import shutil
import subprocess
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

MAX_RESIZE_DIMENSION = 20000

# File extension -> gdk-pixbuf saver type.
SAVE_FORMATS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".bmp": "bmp",
    ".tif": "tiff",
    ".tiff": "tiff",
}


def texture_to_pixbuf(texture):
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write_bytes(texture.save_to_png_bytes())
    loader.close()
    return loader.get_pixbuf()


def resize_texture(texture, width, height):
    pixbuf = texture_to_pixbuf(texture)
    scaled = pixbuf.scale_simple(width, height, GdkPixbuf.InterpType.HYPER)
    return Gdk.Texture.new_for_pixbuf(scaled)


def show_resize_dialog(parent, texture, action_label, on_done):
    """Ask for a new size, then call on_done(resized_texture)."""
    orig_w = texture.get_intrinsic_width()
    orig_h = texture.get_intrinsic_height()
    aspect = orig_h / max(orig_w, 1)

    dialog = Adw.Dialog()
    dialog.set_title("Resize Image")
    dialog.set_content_width(360)

    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_show_end_title_buttons(False)
    header.set_show_start_title_buttons(False)
    cancel = Gtk.Button(label="Cancel")
    cancel.connect("clicked", lambda _b: dialog.close())
    header.pack_start(cancel)
    confirm = Gtk.Button(label=action_label)
    confirm.add_css_class("suggested-action")
    header.pack_end(confirm)
    toolbar.add_top_bar(header)

    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup(description=f"Original size: {orig_w} × {orig_h} px")
    page.add(group)

    width_row = Adw.SpinRow.new_with_range(1, MAX_RESIZE_DIMENSION, 1)
    width_row.set_title("Width")
    width_row.set_value(orig_w)
    height_row = Adw.SpinRow.new_with_range(1, MAX_RESIZE_DIMENSION, 1)
    height_row.set_title("Height")
    height_row.set_value(orig_h)
    percent_row = Adw.SpinRow.new_with_range(1, 1000, 5)
    percent_row.set_title("Scale (%)")
    percent_row.set_value(100)
    lock_row = Adw.SwitchRow(title="Keep Aspect Ratio", active=True)

    for row in (percent_row, width_row, height_row, lock_row):
        group.add(row)

    syncing = False

    def sync(source):
        nonlocal syncing
        if syncing:
            return
        syncing = True
        try:
            locked = lock_row.get_active()
            if source is percent_row:
                pct = percent_row.get_value() / 100
                width_row.set_value(max(1, round(orig_w * pct)))
                height_row.set_value(max(1, round(orig_h * pct)))
            elif source is width_row and locked:
                height_row.set_value(max(1, round(width_row.get_value() * aspect)))
                percent_row.set_value(round(width_row.get_value() / orig_w * 100))
            elif source is height_row and locked:
                width_row.set_value(max(1, round(height_row.get_value() / aspect)))
                percent_row.set_value(round(height_row.get_value() / orig_h * 100))
        finally:
            syncing = False

    for row in (percent_row, width_row, height_row):
        row.connect("notify::value", lambda r, _p: sync(r))

    def on_confirm(_button):
        width = int(width_row.get_value())
        height = int(height_row.get_value())
        dialog.close()
        if (width, height) == (orig_w, orig_h):
            on_done(texture)
        else:
            on_done(resize_texture(texture, width, height))

    confirm.connect("clicked", on_confirm)

    toolbar.set_content(page)
    dialog.set_child(toolbar)
    dialog.present(parent)


def save_texture(parent, texture, on_error=None):
    """Prompt for a file name and save the texture (format from extension)."""
    file_dialog = Gtk.FileDialog()
    file_dialog.set_title("Save Image")
    file_dialog.set_initial_name(f"sticky-image-{time.strftime('%Y%m%d-%H%M%S')}.png")
    pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    if pictures and os.path.isdir(pictures):
        file_dialog.set_initial_folder(Gio.File.new_for_path(pictures))

    filters = Gio.ListStore.new(Gtk.FileFilter)
    for name, patterns in (
        ("PNG Image", ["*.png"]),
        ("JPEG Image", ["*.jpg", "*.jpeg"]),
        ("All Images", [f"*{ext}" for ext in SAVE_FORMATS]),
    ):
        file_filter = Gtk.FileFilter(name=name)
        for pattern in patterns:
            file_filter.add_pattern(pattern)
        filters.append(file_filter)
    file_dialog.set_filters(filters)

    def on_chosen(dlg, result):
        try:
            gfile = dlg.save_finish(result)
        except GLib.Error:
            return  # cancelled
        path = gfile.get_path()
        ext = os.path.splitext(path)[1].lower()
        if ext not in SAVE_FORMATS:
            path += ".png"
            ext = ".png"
        try:
            pixbuf = texture_to_pixbuf(texture)
            if SAVE_FORMATS[ext] in ("jpeg", "bmp") and pixbuf.get_has_alpha():
                pixbuf = _flatten_alpha(pixbuf)
            pixbuf.savev(path, SAVE_FORMATS[ext], [], [])
        except GLib.Error as err:
            if on_error:
                on_error(f"Could not save image: {err.message}")

    file_dialog.save(parent, None, on_chosen)


def _flatten_alpha(pixbuf):
    """Composite onto white so formats without alpha don't go black."""
    w, h = pixbuf.get_width(), pixbuf.get_height()
    flat = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
    flat.fill(0xFFFFFFFF)
    pixbuf.composite(flat, 0, 0, w, h, 0, 0, 1, 1, GdkPixbuf.InterpType.NEAREST, 255)
    return flat


def find_gimp():
    return shutil.which("gimp")


def open_in_gimp(texture):
    """Write the texture to a temp PNG and open it in GIMP.

    Returns an error string, or None on success.
    """
    gimp = find_gimp()
    if gimp is None:
        return "GIMP is not installed"

    # A snap-confined GIMP can't read hidden dirs (~/.cache) or the host /tmp,
    # so give it a file under its own snap data dir in that case.
    real = os.path.realpath(gimp)
    if gimp.startswith("/snap/") or real.startswith("/snap/") or real.endswith("/snap"):
        export_dir = os.path.expanduser("~/snap/gimp/common/sticky-notes")
    else:
        export_dir = os.path.join(GLib.get_user_cache_dir(), "sticky-notes", "gimp")
    os.makedirs(export_dir, exist_ok=True)
    path = os.path.join(export_dir, f"image-{time.strftime('%Y%m%d-%H%M%S')}.png")
    if not texture.save_to_png(path):
        return "Could not write temporary image file"

    try:
        subprocess.Popen(
            [gimp, path],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as err:
        return f"Could not start GIMP: {err}"
    return None
