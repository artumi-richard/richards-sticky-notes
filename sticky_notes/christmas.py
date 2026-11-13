"""Christmas mode decorations: falling snow, holly sprigs and candy canes.

Everything is drawn with GSK paths, so there are no image assets to ship.
"""

import math
import random

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk

CANDY_STRIPE_CSS = """
.xmas-candy-stripe {
    background-image: repeating-linear-gradient(
        -45deg, #d42027 0px, #d42027 6px, #ffffff 6px, #ffffff 12px);
}
"""


def _rgba(hex_color, alpha=1.0):
    rgba = Gdk.RGBA()
    rgba.parse(hex_color)
    rgba.alpha = alpha
    return rgba


def _animations_enabled():
    settings = Gtk.Settings.get_default()
    return settings is None or settings.get_property("gtk-enable-animations")


def _make_dot_texture(radius):
    """A white anti-aliased disc with a 1px clear border, built pixel by pixel.

    Done in plain Python (once) rather than via a renderer, because rendering
    from inside a widget's snapshot pass is not safe.
    """
    size = 2 * radius + 2
    centre = size / 2
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            dist = math.hypot(x + 0.5 - centre, y + 0.5 - centre)
            coverage = max(0.0, min(1.0, radius + 0.5 - dist))
            a = round(coverage * 255)
            pixels += bytes((a, a, a, a))  # premultiplied white
    return Gdk.MemoryTexture.new(
        size, size, Gdk.MemoryFormat.R8G8B8A8_PREMULTIPLIED, GLib.Bytes.new(bytes(pixels)), size * 4
    )


class SnowLayer(Gtk.Widget):
    """Gently falling snowflakes. Ignores input, so clicks pass through it.

    Kept cheap on purpose: it steps on a timer at a modest frame rate rather
    than every display frame (each step repaints the whole board), slows
    right down when the window isn't focused, idles while the window is
    minimised or hidden, and stamps a pre-rendered dot texture per flake
    instead of filling vector circles (~10x cheaper on the GL renderer).
    """

    # (radius range, alpha) per depth layer: small faint flakes read as far away.
    LAYERS = [((0.8, 1.6), 0.45), ((1.6, 2.6), 0.7), ((2.6, 3.8), 0.92)]
    DENSITY = 1 / 3500  # flakes per square pixel
    MAX_FLAKES = 300
    FPS_ACTIVE = 24
    FPS_INACTIVE = 8
    HIDDEN_POLL_MS = 1000
    DOT_RADIUS = 8  # texture radius; scaled down per flake, so stays crisp on HiDPI

    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._flakes = []
        self._size = (0, 0)
        self._timer_id = None
        self._interval = None
        self._last_time = None
        self._running = False
        self._dot = None

    def set_running(self, running):
        self._running = running
        self.set_visible(running)
        if running and _animations_enabled():
            self._schedule()
        else:
            self._cancel()

    def _cancel(self):
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
            self._interval = None

    def _wanted_interval(self):
        root = self.get_root()
        if root is None or not self.get_mapped():
            return self.HIDDEN_POLL_MS
        surface = root.get_surface()
        if surface is not None and isinstance(surface, Gdk.Toplevel):
            hidden = Gdk.ToplevelState.MINIMIZED | getattr(Gdk.ToplevelState, "SUSPENDED", 0)
            if surface.get_state() & hidden:
                return self.HIDDEN_POLL_MS
        fps = self.FPS_ACTIVE if root.is_active() else self.FPS_INACTIVE
        return 1000 // fps

    def _schedule(self):
        interval = self._wanted_interval()
        if interval == self._interval and self._timer_id is not None:
            return
        self._cancel()
        self._interval = interval
        self._timer_id = GLib.timeout_add(interval, self._on_timer)

    def _on_timer(self):
        if self._interval == self.HIDDEN_POLL_MS:
            self._last_time = None  # don't jump forward after being hidden
        else:
            self._step()
        wanted = self._wanted_interval()
        if wanted != self._interval:
            self._timer_id = None
            self._schedule()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _new_flake(self, w, h, anywhere):
        layer = random.randrange(len(self.LAYERS))
        lo, hi = self.LAYERS[layer][0]
        r = random.uniform(lo, hi)
        return {
            "layer": layer,
            "x": random.uniform(0, w),
            "y": random.uniform(-h, h) if anywhere else random.uniform(-40, -r),
            "r": r,
            # Bigger (nearer) flakes fall faster, which sells the depth.
            "speed": random.uniform(14, 22) * r,
            "phase": random.uniform(0, math.tau),
            "freq": random.uniform(0.4, 1.1),
            "sway": random.uniform(4, 18),
        }

    def _sync_size(self):
        w, h = self.get_width(), self.get_height()
        if (w, h) == self._size or w <= 0 or h <= 0:
            return
        old_w = self._size[0]
        self._size = (w, h)
        if old_w:
            for f in self._flakes:
                f["x"] *= w / old_w
        target = max(30, min(self.MAX_FLAKES, int(w * h * self.DENSITY)))
        while len(self._flakes) < target:
            self._flakes.append(self._new_flake(w, h, anywhere=True))
        del self._flakes[target:]

    def _step(self):
        now = GLib.get_monotonic_time() / 1_000_000
        dt = 0 if self._last_time is None else min(0.25, now - self._last_time)
        self._last_time = now
        self._sync_size()
        w, h = self._size
        for f in self._flakes:
            f["y"] += f["speed"] * dt
            f["phase"] += f["freq"] * dt
            if f["y"] - f["r"] > h:
                f.update(self._new_flake(w, h, anywhere=False))
        self.queue_draw()

    def _dot_texture(self):
        if self._dot is None:
            self._dot = _make_dot_texture(self.DOT_RADIUS)
        return self._dot

    def do_snapshot(self, snapshot):
        self._sync_size()
        dot = self._dot_texture()
        # The texture has a 1px transparent border, so scale the rect to match.
        pad = (self.DOT_RADIUS + 1) / self.DOT_RADIUS
        for layer, (_radii, alpha) in enumerate(self.LAYERS):
            snapshot.push_opacity(alpha)
            for f in self._flakes:
                if f["layer"] != layer:
                    continue
                x = f["x"] + math.sin(f["phase"]) * f["sway"]
                r = f["r"] * pad
                snapshot.append_texture(dot, Graphene.Rect().init(x - r, f["y"] - r, 2 * r, 2 * r))
            snapshot.pop()


def _holly_leaf(builder, base_x, base_y, angle, length, half_width, spikes=4):
    """A holly leaf from (base_x, base_y) pointing along ``angle``.

    The edge runs spike tip to spike tip with inward-curving scallops between,
    which is what makes it read as holly rather than a plain oval.
    """
    cos_a, sin_a = math.cos(angle), math.sin(angle)

    def to_world(along, across):
        return base_x + along * cos_a - across * sin_a, base_y + along * sin_a + across * cos_a

    def profile(t):
        # Broad in the middle, a short stalk at the base, a point at the tip.
        return half_width * math.sin(math.pi * min(1.0, t * 1.08)) ** 0.8

    builder.move_to(*to_world(0, 0))
    for side in (1, -1):
        tips = [(i + 0.5) / spikes for i in range(spikes)]
        if side == -1:
            tips = tips[::-1]
        prev = 0.0 if side == 1 else 1.0
        for t in tips:
            mid = (prev + t) / 2
            ctrl = to_world(mid * length, side * profile(mid) * 0.62)
            tip = to_world(t * length, side * profile(t) * 1.18)
            builder.quad_to(*ctrl, *tip)
            prev = t
        end_t = 1.0 if side == 1 else 0.0
        mid = (prev + end_t) / 2
        ctrl = to_world(mid * length, side * profile(mid) * 0.62)
        builder.quad_to(*ctrl, *to_world(end_t * length, 0))
    builder.close()


class HollySprig(Gtk.Widget):
    LEAF = _rgba("#2e7d32")
    RIB = _rgba("#a5d6a7", 0.85)
    BERRY = _rgba("#d32f2f")
    SHINE = _rgba("#ffffff", 0.8)
    # Drawn under the fills so a thin pale rim keeps the sprig visible on
    # green or red notes.
    HALO = _rgba("#ffffff", 0.8)

    def __init__(self):
        super().__init__()
        self.set_size_request(52, 26)
        self.set_valign(Gtk.Align.CENTER)
        self.set_can_target(False)

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        # Berries sit near the top; the two leaves fan down and out beneath them.
        cx, cy = w / 2, h / 2 - 3
        leaves = Gsk.PathBuilder.new()
        ribs = Gsk.PathBuilder.new()
        for angle in (math.radians(152), math.radians(28)):
            _holly_leaf(leaves, cx, cy, angle, 23, 6.5)
            ribs.move_to(cx + 4 * math.cos(angle), cy + 4 * math.sin(angle))
            ribs.line_to(cx + 20 * math.cos(angle), cy + 20 * math.sin(angle))

        halo = Gsk.Stroke.new(2.2)
        halo.set_line_join(Gsk.LineJoin.ROUND)
        leaves_path = leaves.to_path()
        snapshot.append_stroke(leaves_path, halo, self.HALO)
        snapshot.append_fill(leaves_path, Gsk.FillRule.WINDING, self.LEAF)
        rib = Gsk.Stroke.new(0.9)
        rib.set_line_cap(Gsk.LineCap.ROUND)
        snapshot.append_stroke(ribs.to_path(), rib, self.RIB)

        berries = Gsk.PathBuilder.new()
        shine = Gsk.PathBuilder.new()
        for dx, dy in ((-3.5, 1.0), (3.5, 1.0), (0, -3.0)):
            berries.add_circle(Graphene.Point().init(cx + dx, cy + dy), 3.4)
            shine.add_circle(Graphene.Point().init(cx + dx - 1.1, cy + dy - 1.1), 0.9)
        berries_path = berries.to_path()
        snapshot.append_stroke(berries_path, halo, self.HALO)
        snapshot.append_fill(berries_path, Gsk.FillRule.WINDING, self.BERRY)
        snapshot.append_fill(shine.to_path(), Gsk.FillRule.WINDING, self.SHINE)


class CandyCane(Gtk.Widget):
    WHITE = _rgba("#ffffff")
    RED = _rgba("#d42027")

    def __init__(self):
        super().__init__()
        self.set_size_request(16, 24)
        self.set_valign(Gtk.Align.CENTER)
        self.set_can_target(False)

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        x0, y0 = (w - 16) / 2, (h - 24) / 2
        builder = Gsk.PathBuilder.new()
        builder.move_to(x0 + 11, y0 + 22)
        builder.line_to(x0 + 11, y0 + 9)
        builder.cubic_to(x0 + 11, y0 + 1.5, x0 + 3, y0 + 1.5, x0 + 3, y0 + 9)
        path = builder.to_path()

        body = Gsk.Stroke.new(4)
        body.set_line_cap(Gsk.LineCap.ROUND)
        snapshot.append_stroke(path, body, self.WHITE)

        stripes = Gsk.Stroke.new(4)
        stripes.set_dash([2.6, 2.6])
        snapshot.append_stroke(path, stripes, self.RED)
