"""Note colour palette: built-in schemes, user scheme files, and CSS generation.

A palette is an ordered list of slots, each ``{"id", "name", "color"}``. Notes
store the slot *id*, so renaming or recolouring a slot recolours every note
using it. Loading a scheme reuses the existing slot ids positionally, so notes
follow their slot into the new scheme instead of all losing their colour.
"""

import json
import re
import uuid
from pathlib import Path

from gi.repository import GLib

USER_SCHEMES_DIR = Path(GLib.get_user_config_dir()) / "sticky-notes" / "schemes"

DARK_TEXT = "#2b2b2b"
LIGHT_TEXT = "#f2f2f2"

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _scheme(name, *colors):
    return {"name": name, "colors": [{"name": n, "color": c} for n, c in colors]}


# The first scheme's slot ids are the legacy colour names notes were saved
# with before palettes were configurable, so old notes.json files still match.
DEFAULT_SCHEME = _scheme(
    "Pastel (Default)",
    ("Yellow", "#f9e2af"),
    ("Pink", "#f5c2e7"),
    ("Green", "#a6e3a1"),
    ("Blue", "#89b4fa"),
    ("Orange", "#fab387"),
    ("Purple", "#cba6f7"),
    ("Red", "#f38ba8"),
    ("Teal", "#94e2d5"),
    ("Gray", "#bac2de"),
    ("Lavender", "#b4befe"),
)

BUILTIN_SCHEMES = [
    DEFAULT_SCHEME,
    _scheme(
        "Classic Sticky",
        ("Canary", "#fff59d"),
        ("Pink", "#f8bbd0"),
        ("Lime", "#dcedc8"),
        ("Sky", "#b3e5fc"),
        ("Peach", "#ffccbc"),
        ("Lilac", "#e1bee7"),
        ("Mint", "#b2dfdb"),
        ("White", "#fafafa"),
    ),
    _scheme(
        "Soft Rainbow",
        ("Rose", "#ffd6d6"),
        ("Apricot", "#ffe5cc"),
        ("Butter", "#fff5cc"),
        ("Pistachio", "#e0f5d0"),
        ("Aqua", "#d0f0f0"),
        ("Periwinkle", "#d6e4ff"),
        ("Wisteria", "#e8dcff"),
        ("Blush", "#ffdcf0"),
    ),
    _scheme(
        "Nord",
        ("Snow", "#e5e9f0"),
        ("Yellow", "#ebcb8b"),
        ("Green", "#a3be8c"),
        ("Frost", "#88c0d0"),
        ("Blue", "#81a1c1"),
        ("Purple", "#b48ead"),
        ("Orange", "#d08770"),
        ("Red", "#bf616a"),
        ("Teal", "#8fbcbb"),
        ("Night", "#3b4252"),
    ),
    _scheme(
        "Solarized",
        ("Base", "#fdf6e3"),
        ("Base Alt", "#eee8d5"),
        ("Yellow", "#b58900"),
        ("Orange", "#cb4b16"),
        ("Red", "#dc322f"),
        ("Magenta", "#d33682"),
        ("Violet", "#6c71c4"),
        ("Blue", "#268bd2"),
        ("Cyan", "#2aa198"),
        ("Green", "#859900"),
    ),
    _scheme(
        "Gruvbox",
        ("Paper", "#fbf1c7"),
        ("Yellow", "#fabd2f"),
        ("Orange", "#fe8019"),
        ("Red", "#fb4934"),
        ("Pink", "#d3869b"),
        ("Blue", "#83a598"),
        ("Aqua", "#8ec07c"),
        ("Green", "#b8bb26"),
        ("Dark", "#3c3836"),
    ),
    _scheme(
        "Dracula",
        ("Background", "#282a36"),
        ("Current Line", "#44475a"),
        ("Comment", "#6272a4"),
        ("Pink", "#ff79c6"),
        ("Purple", "#bd93f9"),
        ("Cyan", "#8be9fd"),
        ("Green", "#50fa7b"),
        ("Yellow", "#f1fa8c"),
        ("Orange", "#ffb86c"),
        ("Red", "#ff5555"),
    ),
    _scheme(
        "Tokyo Night",
        ("Night", "#1a1b26"),
        ("Storm", "#24283b"),
        ("Dusk", "#414868"),
        ("Blue", "#7aa2f7"),
        ("Magenta", "#bb9af7"),
        ("Green", "#9ece6a"),
        ("Amber", "#e0af68"),
        ("Red", "#f7768e"),
        ("Cyan", "#7dcfff"),
    ),
    _scheme(
        "Earth Tones",
        ("Linen", "#faedcd"),
        ("Sand", "#e9dcc9"),
        ("Sage Light", "#e9edc9"),
        ("Sage", "#ccd5ae"),
        ("Olive", "#a3b18a"),
        ("Caramel", "#d4a373"),
        ("Clay", "#cb997e"),
        ("Mauve", "#b5838d"),
    ),
    _scheme(
        "Ocean",
        ("Foam", "#caf0f8"),
        ("Shallows", "#ade8f4"),
        ("Lagoon", "#90e0ef"),
        ("Surf", "#48cae4"),
        ("Cerulean", "#00b4d8"),
        ("Sea", "#0096c7"),
        ("Deep", "#0077b6"),
        ("Abyss", "#023e8a"),
    ),
    _scheme(
        "Autumn",
        ("Straw", "#ffe8a3"),
        ("Honey", "#ffc971"),
        ("Marigold", "#ffb627"),
        ("Pumpkin", "#ff9505"),
        ("Rust", "#e2711d"),
        ("Burnt Orange", "#cc5803"),
        ("Chestnut", "#a1683a"),
        ("Oxblood", "#6f1d1b"),
    ),
    _scheme(
        "Neon",
        ("Lemon", "#fffb00"),
        ("Lime", "#39ff14"),
        ("Cyan", "#00fff7"),
        ("Magenta", "#ff2fd5"),
        ("Orange", "#ff6b00"),
        ("Violet", "#b026ff"),
        ("Hot Pink", "#ff1f6d"),
    ),
    _scheme(
        "Christmas",
        ("Snow", "#f8f8f2"),
        ("Cranberry", "#c62828"),
        ("Holly", "#2e7d32"),
        ("Gold", "#f9d56e"),
        ("Pine", "#a5d6a7"),
        ("Candy", "#ffcdd2"),
        ("Frost", "#e3f2fd"),
        ("Gingerbread", "#c8a27c"),
    ),
    _scheme(
        "Monochrome",
        ("White", "#ffffff"),
        ("Mist", "#eeeeee"),
        ("Silver", "#d9d9d9"),
        ("Ash", "#bdbdbd"),
        ("Steel", "#9e9e9e"),
        ("Graphite", "#616161"),
        ("Charcoal", "#424242"),
        ("Ink", "#212121"),
    ),
]


DEFAULT_BACKGROUND = ["#2e3440", "#4c566a", "#5e81ac"]

# Board background gradient (top-left to bottom-right) for each built-in scheme,
# chosen so the scheme's notes stand out against it.
_SCHEME_BACKGROUNDS = {
    "Pastel (Default)": DEFAULT_BACKGROUND,
    "Classic Sticky": ["#7b5b3e", "#946d4a", "#a98159"],  # cork board
    "Soft Rainbow": ["#4a4e80", "#6a5b8e", "#9a6a98"],
    "Nord": ["#242933", "#2e3440", "#3b4252"],
    "Solarized": ["#002b36", "#073642", "#0b4a5a"],
    "Gruvbox": ["#1d2021", "#282828", "#3c3836"],
    "Dracula": ["#3a2f5c", "#4b3a73", "#6a4c93"],
    "Tokyo Night": ["#2a2f4a", "#3d4466", "#565f89"],
    "Earth Tones": ["#3e4a3d", "#4f5a45", "#6b705c"],
    "Ocean": ["#f1e3c6", "#e6d3a8", "#d9c08c"],  # sandy beach
    "Autumn": ["#2d1e17", "#3d271b", "#4f3322"],
    "Neon": ["#0d0221", "#1a0b3d", "#2b0f54"],
    "Christmas": ["#0b1d2e", "#12324a", "#1b4d3e"],  # winter night into pine
    "Monochrome": ["#4f6070", "#6b7f8f", "#8fa3b2"],
}
for _s in BUILTIN_SCHEMES:
    _s["background"] = list(_SCHEME_BACKGROUNDS.get(_s["name"], DEFAULT_BACKGROUND))


def sanitize_background(raw):
    """1–3 hex gradient stops (one stop = solid colour); default if unusable."""
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list):
        stops = [str(c).lower() for c in raw if _HEX_RE.match(str(c))][:3]
        if stops:
            return stops
    return list(DEFAULT_BACKGROUND)


def build_background_css(stops):
    if len(stops) == 1:
        value = stops[0]
    else:
        value = "linear-gradient(135deg, " + ", ".join(
            f"{c} {round(i * 100 / (len(stops) - 1))}%" for i, c in enumerate(stops)
        ) + ")"
    return f".board-background {{ background: {value}; }}\n"


def new_slot_id():
    return "c" + uuid.uuid4().hex[:8]


def default_palette():
    return [
        {"id": c["name"].lower(), "name": c["name"], "color": c["color"]}
        for c in DEFAULT_SCHEME["colors"]
    ]


def sanitize_palette(raw):
    """Validate a palette loaded from disk; fall back to the default if unusable."""
    palette = []
    seen = set()
    if isinstance(raw, list):
        for slot in raw:
            if not isinstance(slot, dict):
                continue
            color = str(slot.get("color", ""))
            if not _HEX_RE.match(color):
                continue
            slot_id = str(slot.get("id", ""))
            if not _ID_RE.match(slot_id) or slot_id in seen:
                slot_id = new_slot_id()
            seen.add(slot_id)
            palette.append(
                {"id": slot_id, "name": str(slot.get("name") or "Color"), "color": color.lower()}
            )
    return palette or default_palette()


def apply_scheme(palette, scheme, append=False):
    """Return a new palette from ``scheme``.

    Replacing keeps the current slot ids in order, so notes keep their slot
    position (slot 1 stays slot 1, now in the new colour). Appending adds the
    scheme's colours as new slots after the existing ones.
    """
    colors = scheme["colors"]
    if append:
        return [dict(s) for s in palette] + [
            {"id": new_slot_id(), "name": c["name"], "color": c["color"]} for c in colors
        ]
    ids = [s["id"] for s in palette]
    return [
        {
            "id": ids[i] if i < len(ids) else new_slot_id(),
            "name": c["name"],
            "color": c["color"],
        }
        for i, c in enumerate(colors)
    ]


def load_user_schemes():
    """Read extra schemes from ``~/.config/sticky-notes/schemes/*.json``.

    Each file is ``{"name": "...", "colors": [{"name": "...", "color": "#rrggbb"}, ...]}``,
    with an optional ``"background": ["#rrggbb", ...]`` of 1–3 gradient stops.
    """
    schemes = []
    try:
        files = sorted(USER_SCHEMES_DIR.glob("*.json"))
    except OSError:
        return schemes
    for path in files:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        colors = [
            {"name": str(c.get("name") or "Color"), "color": str(c["color"]).lower()}
            for c in data.get("colors", [])
            if isinstance(c, dict) and _HEX_RE.match(str(c.get("color", "")))
        ]
        if colors:
            scheme = {"name": str(data.get("name") or path.stem), "colors": colors}
            if data.get("background"):
                scheme["background"] = sanitize_background(data["background"])
            schemes.append(scheme)
    return schemes


def all_schemes():
    return BUILTIN_SCHEMES + load_user_schemes()


def _luminance(hex_color):
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(a, b):
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def text_color_for(hex_color):
    """Pick dark or light text for readable contrast on ``hex_color``."""
    luminance = _luminance(hex_color)
    # Contrast against near-black vs near-white; pick whichever is higher.
    return DARK_TEXT if (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) else LIGHT_TEXT


DEFAULT_LINK = "#1e66f5"
# Tried in order; the first that is readable (WCAG AA, 4.5:1) on the note wins.
# Blues first so links still look like links, then other hues for notes
# where no blue stands out (e.g. mid-blue notes).
LINK_CANDIDATES = [
    DEFAULT_LINK,
    "#0b3d91",  # deep blue, for light-to-mid backgrounds
    "#9fd0ff",  # pale blue, for dark backgrounds
    "#ffe066",  # pale yellow, for dark blue backgrounds
    "#5a0f78",  # deep purple
    "#000000",
    "#ffffff",
]
MIN_LINK_CONTRAST = 4.5


def link_color_for(hex_color):
    """A link colour that stays readable on ``hex_color``."""
    for candidate in LINK_CANDIDATES:
        if contrast_ratio(candidate, hex_color) >= MIN_LINK_CONTRAST:
            return candidate
    return max(LINK_CANDIDATES, key=lambda c: contrast_ratio(c, hex_color))


# Christmas mode note titles: always a red, picked like link colours so a
# title stays readable on red, green or dark notes.
TITLE_CANDIDATES = [
    "#c62828",  # festive red
    "#8e0000",  # deep red, for mid-tone notes
    "#ff8a80",  # light red, for dark notes
    "#ffcdd2",  # pale pink-red, for red notes
    "#5c0000",  # darkest red, for bright mid-tone notes
    "#ffe4e6",  # palest red, for saturated red/green notes
]


def title_color_for(hex_color):
    for candidate in TITLE_CANDIDATES:
        if contrast_ratio(candidate, hex_color) >= MIN_LINK_CONTRAST:
            return candidate
    return max(TITLE_CANDIDATES, key=lambda c: contrast_ratio(c, hex_color))


def slot_color(palette, slot_id):
    """The hex colour for ``slot_id``, or the first slot's (matches the CSS fallback)."""
    for slot in palette:
        if slot["id"] == slot_id:
            return slot["color"]
    return palette[0]["color"]


def build_palette_css(palette):
    # Base rule first: a note whose slot was deleted shows the first colour
    # (same specificity, so the per-slot rules below win when they match).
    first = palette[0]["color"]
    rules = [
        f".note-card {{ background-color: {first}; }}",
        f".note-card .note-text, .note-card .note-text text, .note-card .note-handle "
        f"{{ color: {text_color_for(first)}; }}",
    ]
    for slot in palette:
        cls = f"note-color-{slot['id']}"
        fg = text_color_for(slot["color"])
        rules.append(f".{cls} {{ background-color: {slot['color']}; }}")
        rules.append(
            f".{cls} .note-text, .{cls} .note-text text, .{cls} .note-handle "
            f"{{ color: {fg}; }}"
        )
    return "\n".join(rules) + "\n"
