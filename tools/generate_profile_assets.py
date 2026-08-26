"""Generate the accessible static SVG and animated GIF profile banners.

The SVGs are deliberately static: GitHub renders SVG in profile READMEs but
does not run SVG animation. The GIFs carry only the non-essential pulse motion.
Run this script whenever profile facts or the visual design changes.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PORTRAIT_REFERENCE = ROOT / "assets" / "profile" / "portrait-dither-reference.png"
WIDTH, HEIGHT = 1180, 610
FRAME_COUNT = 36
# GIF timing is quantized in hundredths of a second. This mix is exactly 14.2 s.
FRAME_DURATIONS_MS = (400,) * 24 + (390,) * 4 + (380,) * 8
LOOP_SECONDS = sum(FRAME_DURATIONS_MS) / 1000
INTRO_SECONDS = 3.2
PORTRAIT_CROP = (120, 0, 1134, 1050)
PORTRAIT_SIZE = (196, 248)
PORTRAIT_POSITION = (168, 166)

ROWS: tuple[tuple[str, str], ...] = (
    ("SUBJECT", "Renan Augusto"),
    ("ROLE", "Software Engineer"),
    ("FOCUS", "Game Dev / Embedded"),
    ("STATUS", "Building"),
    ("TOOLCHAIN", "Unity / Unreal / ESP32"),
    ("CORE.ENGINE", "Unity / Unreal"),
    ("CORE.HARDWARE", "ESP32 / Automation"),
    ("GRID.MAIL", "renanaugustokwn@outlook.com"),
    ("GRID.LINKEDIN", "renan-augusto-kwn"),
    ("GRID.GITHUB", "@RenanAugustoKwn"),
)

NODES: tuple[tuple[str, tuple[int, int, int, int], tuple[int, int]], ...] = (
    ("SOFTWARE", (74, 209, 128, 42), (222, 267)),
    ("GAME DEV", (331, 209, 122, 42), (329, 267)),
    ("EMBEDDED", (68, 432, 139, 42), (224, 395)),
    ("AUTOMATION", (322, 432, 139, 42), (330, 395)),
)

THEMES = {
    "dark": {
        "background": "#0A101F",
        "surface": "#0D1529",
        "surface_alt": "#111C34",
        "panel": "#10192D",
        "border": "#314763",
        "text": "#F6F8FF",
        "muted": "#98A8C2",
        "portrait": "#A78BFA",
        "ui": "#22D3EE",
        "accent": "#10B981",
        "node_fill": "#151A35",
        "shadow": "#050814",
    },
    "light": {
        "background": "#F4F7FF",
        "surface": "#FFFFFF",
        "surface_alt": "#EAF1FF",
        "panel": "#F8FAFF",
        "border": "#B5C8E7",
        "text": "#111827",
        "muted": "#52627D",
        "portrait": "#7C3AED",
        "ui": "#0891B2",
        "accent": "#057A55",
        "node_fill": "#FFFFFF",
        "shadow": "#DCE7FA",
    },
}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def with_alpha(value: str, alpha: int) -> tuple[int, int, int, int]:
    return (*hex_to_rgb(value), alpha)


def blend_rgb(
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
    opacity: float,
) -> tuple[int, int, int]:
    """Blend a semantic color into a panel without relying on GIF alpha."""
    bounded = min(1.0, max(0.0, opacity))
    return tuple(
        round(channel_background + (channel_foreground - channel_background) * bounded)
        for channel_foreground, channel_background in zip(foreground, background)
    )


def elapsed_seconds(frame_index: int) -> float:
    return sum(FRAME_DURATIONS_MS[:frame_index]) / 1000


def ramp(value: float) -> float:
    """A compact smoothstep used by the boot reveal."""
    bounded = min(1.0, max(0.0, value))
    return bounded * bounded * (3 - 2 * bounded)


def row_reveal(elapsed: float, row_index: int) -> float:
    """Keep every fact visible while progressively strengthening it at boot."""
    if elapsed >= INTRO_SECONDS:
        return 1.0
    delay = 0.12 + row_index * 0.23
    return 0.56 + 0.44 * ramp((elapsed - delay) / 0.72)


def active_system_row(elapsed: float) -> int:
    if elapsed < INTRO_SECONDS:
        return min(len(ROWS) - 1, int(elapsed / INTRO_SECONDS * len(ROWS)))
    scan_progress = (elapsed - INTRO_SECONDS) / (LOOP_SECONDS - INTRO_SECONDS)
    return int(scan_progress * len(ROWS)) % len(ROWS)


def svg_row_y(index: int) -> float:
    return 183 + index * 34.0


def gif_row_y(index: int) -> float:
    return 173 + index * 34.0


@lru_cache(maxsize=1)
def portrait_mask() -> Image.Image:
    """Return the supplied, identity-preserving portrait as a compact 1-bit mask."""
    if not PORTRAIT_REFERENCE.exists():
        raise FileNotFoundError(
            f"Missing portrait reference: {PORTRAIT_REFERENCE.relative_to(ROOT)}"
        )
    source = Image.open(PORTRAIT_REFERENCE).convert("L")
    portrait = source.crop(PORTRAIT_CROP).resize(PORTRAIT_SIZE, Image.Resampling.LANCZOS)
    # The source is a two-tone dither image: retain its bright marks only.
    return portrait.point(lambda value: 255 if value >= 90 else 0, mode="1")


def portrait_paths() -> str:
    """Encode the 1-bit portrait as path runs, never as a raster <image> in SVG."""
    mask = portrait_mask()
    x_origin, y_origin = PORTRAIT_POSITION
    paths: list[str] = []
    for y in range(mask.height):
        x = 0
        while x < mask.width:
            if not mask.getpixel((x, y)):
                x += 1
                continue
            start = x
            while x < mask.width and mask.getpixel((x, y)):
                x += 1
            length = x - start
            paths.append(
                f'<path d="M{x_origin + start} {y_origin + y}h{length}v1h-{length}z"/>'
            )
    return "\n        ".join(paths)


def leader(label: str) -> str:
    return f"{label} {'·' * max(4, 22 - len(label))}"


def row_svg(index: int, label: str, value: str, theme: dict[str, str]) -> str:
    y = svg_row_y(index)
    label_color = theme["accent"] if label.startswith("CORE.") else (
        theme["ui"] if label.startswith("GRID.") else theme["muted"]
    )
    # Keep the declarative alignment requested by the visual specification
    # without horizontally distorting short values in real browser rendering.
    value_length = max(74, min(302, round(len(value) * 8.45)))
    return (
        f'<text x="526" y="{y:.1f}" fill="{label_color}" font-size="14" '
        f'textLength="246" lengthAdjust="spacing">{escape(leader(label))}</text>\n'
        f'      <text x="790" y="{y:.1f}" fill="{theme["text"]}" font-size="14" '
        f'textLength="{value_length}" lengthAdjust="spacing">{escape(value)}</text>'
    )


def svg_node(label: str, box: tuple[int, int, int, int], target: tuple[int, int], theme: dict[str, str], index: int) -> str:
    x, y, w, h = box
    tx, ty = target
    center_x = x + w / 2
    center_y = y + h / 2
    color = (theme["ui"], theme["portrait"], theme["accent"], theme["ui"])[index]
    return f'''
      <path d="M{center_x:.1f} {center_y:.1f} L{tx} {ty}" fill="none" stroke="{color}" stroke-width="2" stroke-opacity=".54" stroke-dasharray="4 8"/>
      <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="11" fill="{theme["node_fill"]}" stroke="{color}" stroke-width="1.5"/>
      <text x="{center_x:.1f}" y="{y + 26}" text-anchor="middle" fill="{theme["text"]}" font-size="15" font-weight="700" letter-spacing=".8">{label}</text>'''


def render_svg(theme_name: str) -> str:
    theme = THEMES[theme_name]
    nodes = "\n".join(
        svg_node(label, box, target, theme, index).strip()
        for index, (label, box, target) in enumerate(NODES)
    )
    rows = "\n      ".join(
        row_svg(index, label, value, theme)
        for index, (label, value) in enumerate(ROWS)
    )
    portrait = portrait_paths()
    title = f"Renan Augusto - {theme_name} technical profile"
    desc = (
        "Static accessible terminal profile. The Visual Map connects software, "
        "game development, embedded systems and automation to an abstract "
        "portrait traced as one-bit SVG paths; only verified public profile "
        "facts are included."
    )
    return (
        f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1180" height="610" viewBox="0 0 1180 610" role="img" aria-labelledby="title desc">
  <title id="title">{escape(title)}</title>
  <desc id="desc">{escape(desc)}</desc>
  <defs>
    <linearGradient id="header" x1="0" y1="0" x2="1" y2="0">
      <stop stop-color="{theme["surface_alt"]}"/>
      <stop offset="1" stop-color="{theme["surface"]}"/>
    </linearGradient>
    <linearGradient id="portraitFill" x1="0" y1="0" x2="1" y2="1">
      <stop stop-color="{theme["portrait"]}" stop-opacity=".22"/>
      <stop offset="1" stop-color="{theme["ui"]}" stop-opacity=".08"/>
    </linearGradient>
  </defs>
  <rect width="1180" height="610" rx="24" fill="{theme["background"]}"/>
  <rect x="24" y="20" width="1132" height="570" rx="18" fill="{theme["surface"]}" stroke="{theme["border"]}" stroke-width="2"/>
  <path d="M42 85H1138" stroke="{theme["border"]}" stroke-width="2"/>
  <rect x="25" y="21" width="1130" height="63" rx="17" fill="url(#header)"/>
  <circle cx="57" cy="53" r="7" fill="#FB7185"/>
  <circle cx="81" cy="53" r="7" fill="#FBBF24"/>
  <circle cx="105" cy="53" r="7" fill="{theme["accent"]}"/>
  <text x="590" y="60" text-anchor="middle" fill="{theme["text"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="18" font-weight="700">profile.sh --live</text>
  <rect x="927" y="38" width="190" height="29" rx="14.5" fill="{theme["panel"]}" stroke="{theme["ui"]}" stroke-opacity=".72"/>
  <circle cx="947" cy="52.5" r="4" fill="{theme["accent"]}"/>
  <text x="962" y="57" fill="{theme["text"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="13" font-weight="700">@RenanAugustoKwn</text>

  <rect x="49" y="110" width="437" height="420" rx="15" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="1.5"/>
  <text x="74" y="145" fill="{theme["ui"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="17" font-weight="700" letter-spacing="1.4">VISUAL.MAP</text>
  <text x="459" y="145" text-anchor="end" fill="{theme["muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="12">4 LINKED DISCIPLINES</text>
  <path d="M74 160H461" stroke="{theme["border"]}" stroke-width="1"/>

  <rect x="162" y="160" width="208" height="260" rx="14" fill="url(#portraitFill)" stroke="{theme["portrait"]}" stroke-opacity=".58"/>
  <g fill="{theme["portrait"]}">{portrait}</g>
  <path d="M181 423H351" stroke="{theme["portrait"]}" stroke-opacity=".56" stroke-width="1" stroke-dasharray="4 8"/>
  <rect x="211" y="332" width="110" height="43" rx="11" fill="{theme["surface"]}" stroke="{theme["portrait"]}" stroke-width="1.5"/>
  <text x="266" y="350" text-anchor="middle" fill="{theme["text"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="15" font-weight="700">RENAN</text>
  <text x="266" y="367" text-anchor="middle" fill="{theme["muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="11" letter-spacing="1.1">CORE SIGNAL</text>
  {nodes}
  <text x="74" y="507" fill="{theme["muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="12">STATIC CORE + ANIMATED PULSE</text>

  <rect x="512" y="110" width="620" height="420" rx="15" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="1.5"/>
  <text x="526" y="145" fill="{theme["ui"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="17" font-weight="700" letter-spacing="1.4">SYSTEM.INFO</text>
  <text x="1110" y="145" text-anchor="end" fill="{theme["muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="12">PUBLIC / VERIFIED FIELDS</text>
  <path d="M526 160H1110" stroke="{theme["border"]}" stroke-width="1"/>
  <g font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace">
      {rows}
  </g>
  <path d="M526 541H1110" stroke="{theme["border"]}" stroke-width="1"/>
  <text x="526" y="562" fill="{theme["muted"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="12">$ build / learn / ship / repeat</text>
  <text x="1110" y="562" text-anchor="end" fill="{theme["accent"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="12">SYSTEM READY</text>
</svg>
'''.rstrip()
        + "\n"
    )


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    font_name = "consolab.ttf" if bold else "consola.ttf"
    candidates = (
        Path("C:/Windows/Fonts") / font_name,
        Path("C:/Windows/Fonts/DejaVuSansMono.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    fill: tuple[int, int, int, int],
    *,
    width: int = 2,
    dash: float = 7,
    gap: float = 8,
) -> None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if not length:
        return
    ux, uy = dx / length, dy / length
    cursor = 0.0
    while cursor < length:
        next_cursor = min(cursor + dash, length)
        draw.line(
            (
                start[0] + ux * cursor,
                start[1] + uy * cursor,
                start[0] + ux * next_cursor,
                start[1] + uy * next_cursor,
            ),
            fill=fill,
            width=width,
        )
        cursor += dash + gap


def draw_centered(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int] | tuple[int, int, int, int],
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((center[0] - (box[2] - box[0]) / 2, center[1] - (box[3] - box[1]) / 2), text, font=font, fill=fill)


def draw_gif_frame(theme_name: str, frame_index: int) -> Image.Image:
    theme = THEMES[theme_name]
    elapsed = elapsed_seconds(frame_index)
    progress = elapsed / LOOP_SECONDS
    intro_progress = min(1.0, elapsed / INTRO_SECONDS)
    active_row = active_system_row(elapsed)
    active_route = int(progress * len(NODES)) % len(NODES)
    image = Image.new("RGB", (WIDTH, HEIGHT), hex_to_rgb(theme["background"]))
    draw = ImageDraw.Draw(image)
    mono12 = get_font(12)
    mono13 = get_font(13)
    mono14 = get_font(14)
    mono15 = get_font(15, bold=True)
    mono17 = get_font(17, bold=True)
    mono18 = get_font(18, bold=True)

    # Terminal shell.
    draw.rounded_rectangle((24, 20, 1156, 590), radius=18, fill=hex_to_rgb(theme["surface"]), outline=hex_to_rgb(theme["border"]), width=2)
    draw.rounded_rectangle((25, 21, 1155, 84), radius=17, fill=hex_to_rgb(theme["surface_alt"]))
    draw.line((42, 85, 1138, 85), fill=hex_to_rgb(theme["border"]), width=2)
    for x, color in ((57, "#FB7185"), (81, "#FBBF24"), (105, theme["accent"])):
        draw.ellipse((x - 7, 46, x + 7, 60), fill=hex_to_rgb(color))
    draw_centered(draw, (590, 55), "profile.sh --live", mono18, hex_to_rgb(theme["text"]))
    draw.rounded_rectangle((927, 38, 1117, 67), radius=15, fill=hex_to_rgb(theme["panel"]), outline=hex_to_rgb(theme["ui"]), width=1)
    draw.ellipse((943, 49, 951, 57), fill=hex_to_rgb(theme["accent"]))
    draw.text((962, 45), "@RenanAugustoKwn", font=mono13, fill=hex_to_rgb(theme["text"]))

    # Panels and headings.
    draw.rounded_rectangle((49, 110, 486, 530), radius=15, fill=hex_to_rgb(theme["panel"]), outline=hex_to_rgb(theme["border"]), width=2)
    draw.rounded_rectangle((512, 110, 1132, 530), radius=15, fill=hex_to_rgb(theme["panel"]), outline=hex_to_rgb(theme["border"]), width=2)
    draw.text((74, 130), "VISUAL.MAP", font=mono17, fill=hex_to_rgb(theme["ui"]))
    right_text = "4 LINKED DISCIPLINES"
    right_box = draw.textbbox((0, 0), right_text, font=mono12)
    draw.text((461 - (right_box[2] - right_box[0]), 133), right_text, font=mono12, fill=hex_to_rgb(theme["muted"]))
    draw.line((74, 160, 461, 160), fill=hex_to_rgb(theme["border"]), width=1)
    draw.text((526, 130), "SYSTEM.INFO", font=mono17, fill=hex_to_rgb(theme["ui"]))
    if elapsed < INTRO_SECONDS:
        header_text = f"BOOT SEQUENCE / {round(intro_progress * 100):03d}%"
    else:
        header_text = f"LIVE SCAN / {active_row + 1:02d}/{len(ROWS):02d}"
    header_box = draw.textbbox((0, 0), header_text, font=mono12)
    draw.text((1110 - (header_box[2] - header_box[0]), 133), header_text, font=mono12, fill=hex_to_rgb(theme["muted"]))
    draw.line((526, 160, 1110, 160), fill=hex_to_rgb(theme["border"]), width=1)

    # Identity-preserving dithered portrait. The published SVG uses the same
    # source as individual paths; the GIF uses a 1-bit mask for compactness.
    portrait = hex_to_rgb(theme["portrait"])
    panel_color = hex_to_rgb(theme["panel"])
    map_strength = 0.74 + 0.26 * ramp(intro_progress)
    portrait_tint = blend_rgb(portrait, panel_color, map_strength)
    px, py = PORTRAIT_POSITION
    pw, ph = PORTRAIT_SIZE
    draw.rounded_rectangle((px - 6, py - 6, px + pw + 6, py + ph + 6), radius=14, fill=hex_to_rgb(theme["surface_alt"]), outline=portrait_tint, width=1)
    image.paste(Image.new("RGB", PORTRAIT_SIZE, portrait_tint), PORTRAIT_POSITION, portrait_mask())
    draw = ImageDraw.Draw(image)
    orbit = (elapsed / 3.55) % 1
    radius = 48 + orbit * 96
    ring_color = blend_rgb(
        hex_to_rgb(theme["ui"]),
        panel_color,
        0.14 + 0.25 * (1 - orbit),
    )
    draw.ellipse((266 - radius, 292 - radius, 266 + radius, 292 + radius), outline=ring_color, width=1)
    draw.line((181, 423, 351, 423), fill=portrait_tint, width=1)

    # Base connectors plus a moving, low-frequency pulse.
    route_colors = (theme["ui"], theme["portrait"], theme["accent"], theme["ui"])
    node_centers: list[tuple[float, float]] = []
    for index, (label, box, target) in enumerate(NODES):
        x, y, w, h = box
        center = (x + w / 2, y + h / 2)
        node_centers.append(center)
        route_color = route_colors[index]
        route_rgb = hex_to_rgb(route_color)
        node_strength = 0.62 + 0.38 * ramp((elapsed - index * 0.24) / 1.1)
        dashed_line(
            draw,
            center,
            target,
            blend_rgb(route_rgb, panel_color, 0.34 + 0.32 * node_strength),
            width=2,
        )
        active = index == active_route
        outline = blend_rgb(route_rgb, panel_color, node_strength)
        fill = hex_to_rgb(theme["node_fill"])
        draw.rounded_rectangle((x, y, x + w, y + h), radius=11, fill=fill, outline=outline, width=2 if active else 1)
        draw_centered(
            draw,
            (center[0], center[1] + 1),
            label,
            mono15,
            blend_rgb(hex_to_rgb(theme["text"]), fill, node_strength),
        )

        pulse_progress = (progress * 1.25 - index / 4) % 1
        px = center[0] + (target[0] - center[0]) * pulse_progress
        py = center[1] + (target[1] - center[1]) * pulse_progress
        pulse = Image.new("RGBA", image.size, (0, 0, 0, 0))
        pdraw = ImageDraw.Draw(pulse)
        pdraw.ellipse((px - 12, py - 12, px + 12, py + 12), fill=with_alpha(route_color, 36))
        pdraw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=with_alpha(route_color, 245))
        image = Image.alpha_composite(image.convert("RGBA"), pulse).convert("RGB")
        draw = ImageDraw.Draw(image)

    # Core label stays fully readable in every frame.
    core_strength = 0.72 + 0.28 * ramp(intro_progress)
    draw.rounded_rectangle((211, 332, 321, 375), radius=11, fill=hex_to_rgb(theme["surface"]), outline=portrait_tint, width=2)
    draw_centered(draw, (266, 349), "RENAN", mono15, blend_rgb(hex_to_rgb(theme["text"]), panel_color, core_strength))
    draw_centered(draw, (266, 367), "CORE SIGNAL", mono12, blend_rgb(hex_to_rgb(theme["muted"]), panel_color, core_strength))
    active_name = NODES[active_route][0]
    if elapsed < INTRO_SECONDS:
        map_status = f"MAP BOOT / {round(intro_progress * 100):03d}%"
    else:
        map_status = f"ACTIVE ROUTE / {active_name}"
    draw.text((74, 500), map_status, font=mono12, fill=hex_to_rgb(theme["muted"]))

    # System fields: an accessibility-safe boot reveal followed by a live scan.
    # Values never disappear, so the first GIF frame remains self-contained.
    for index, (label, value) in enumerate(ROWS):
        y = gif_row_y(index)
        label_hex = theme["accent"] if label.startswith("CORE.") else (
            theme["ui"] if label.startswith("GRID.") else theme["muted"]
        )
        is_active = index == active_row
        row_strength = row_reveal(elapsed, index)
        if elapsed >= INTRO_SECONDS and not is_active:
            row_strength = 0.78
        if is_active:
            y_int = round(y)
            draw.rounded_rectangle(
                (520, y_int - 7, 1122, y_int + 14),
                radius=5,
                fill=blend_rgb(hex_to_rgb(theme["ui"]), panel_color, 0.105),
            )
            draw.rectangle(
                (520, y_int - 7, 523, y_int + 14),
                fill=blend_rgb(hex_to_rgb(theme["ui"]), panel_color, 0.88),
            )
            draw.ellipse(
                (1103, y_int - 1, 1109, y_int + 5),
                fill=blend_rgb(hex_to_rgb(theme["accent"]), panel_color, 0.92),
            )
            row_strength = 1.0
        draw.text(
            (526, y),
            leader(label).replace("·", "."),
            font=mono14,
            fill=blend_rgb(hex_to_rgb(label_hex), panel_color, row_strength),
        )
        draw.text(
            (790, y),
            value,
            font=mono14,
            fill=blend_rgb(hex_to_rgb(theme["text"]), panel_color, row_strength),
        )
    draw.line((526, 541, 1110, 541), fill=hex_to_rgb(theme["border"]), width=1)
    draw.text((526, 551), "$ build / learn / ship / repeat", font=mono12, fill=hex_to_rgb(theme["muted"]))
    state_text = (
        f"INDEXING / {active_row + 1:02d}/{len(ROWS):02d}"
        if elapsed < INTRO_SECONDS
        else "SYSTEM READY"
    )
    state_box = draw.textbbox((0, 0), state_text, font=mono12)
    draw.text(
        (1110 - (state_box[2] - state_box[0]), 551),
        state_text,
        font=mono12,
        fill=hex_to_rgb(theme["accent"]),
    )
    return image


def write_gif(theme_name: str) -> None:
    frames = [draw_gif_frame(theme_name, index) for index in range(FRAME_COUNT)]
    palette = frames[0].quantize(colors=48, method=Image.Quantize.MEDIANCUT)
    indexed_frames = [
        frame.quantize(palette=palette, dither=Image.Dither.NONE)
        for frame in frames
    ]
    indexed_frames[0].save(
        ROOT / f"visual-map-{theme_name}.gif",
        save_all=True,
        append_images=indexed_frames[1:],
        duration=FRAME_DURATIONS_MS,
        loop=0,
        disposal=2,
        optimize=True,
    )


def main() -> None:
    for theme_name in THEMES:
        (ROOT / f"{theme_name}.svg").write_text(
            render_svg(theme_name), encoding="utf-8", newline="\n"
        )
        write_gif(theme_name)


if __name__ == "__main__":
    main()
