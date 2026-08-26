"""Generate the accessible static SVG and animated GIF profile banners.

The SVGs are deliberately static: GitHub renders SVG in profile READMEs but
does not run SVG animation. The GIFs carry only the non-essential pulse motion.
Run this script whenever profile facts or the visual design changes.
"""

from __future__ import annotations

import math
import random
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
PORTRAIT_CROP = (172, 0, 1012, 1050)
PORTRAIT_SIZE = (256, 320)
PORTRAIT_POSITION = (139, 174)
MAP_BOUNDS = (95, 169, 440, 506)
PARTICLE_COUNT = 4_800

# The visual sequence deliberately comes back to the portrait.  That makes the
# first and final frames compatible enough for a calm, seamless GIF loop.
MORPH_PHASES: tuple[tuple[str, str, float, float], ...] = (
    ("portrait", "portrait", 0.0, 2.4),
    ("portrait", "csharp", 2.4, 3.6),
    ("csharp", "csharp", 3.6, 4.8),
    ("csharp", "flutter", 4.8, 6.0),
    ("flutter", "flutter", 6.0, 7.2),
    ("flutter", "cplusplus", 7.2, 8.4),
    ("cplusplus", "cplusplus", 8.4, 9.6),
    ("cplusplus", "portrait", 9.6, 11.2),
    ("portrait", "portrait", 11.2, LOOP_SECONDS),
)

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
        "shadow": "#DCE7FA",
    },
}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


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


def lerp_rgb(
    first: tuple[int, int, int], second: tuple[int, int, int], progress: float
) -> tuple[int, int, int]:
    bounded = min(1.0, max(0.0, progress))
    return tuple(
        round(start + (end - start) * bounded)
        for start, end in zip(first, second)
    )


def morph_state(elapsed: float) -> tuple[str, str, float]:
    """Return the current source, target, and raw transition progress."""
    for source, target, start, end in MORPH_PHASES:
        if elapsed < end:
            if source == target:
                return source, target, 0.0
            return source, target, (elapsed - start) / (end - start)
    return "portrait", "portrait", 0.0


@lru_cache(maxsize=None)
def language_mask(stage: str) -> Image.Image:
    """Draw original, code-native glyph masks for the particle targets."""
    if stage not in {"csharp", "flutter", "cplusplus"}:
        raise ValueError(f"Unsupported language particle target: {stage}")

    mask = Image.new("L", PORTRAIT_SIZE, 0)
    draw = ImageDraw.Draw(mask)
    center = (PORTRAIT_SIZE[0] // 2, PORTRAIT_SIZE[1] // 2)

    if stage in {"csharp", "cplusplus"}:
        radius = 92
        points = [
            (
                round(center[0] + radius * math.cos(math.radians(30 + index * 60))),
                round(center[1] + radius * math.sin(math.radians(30 + index * 60))),
            )
            for index in range(6)
        ]
        draw.line(points + [points[0]], fill=255, width=9, joint="curve")
        glyph = "C#" if stage == "csharp" else "C++"
        font = get_font(58 if stage == "csharp" else 48, bold=True)
        glyph_box = draw.textbbox((0, 0), glyph, font=font, stroke_width=1)
        draw.text(
            (
                center[0] - (glyph_box[2] - glyph_box[0]) / 2,
                center[1] - (glyph_box[3] - glyph_box[1]) / 2 - 4,
            ),
            glyph,
            font=font,
            fill=255,
            stroke_width=1,
            stroke_fill=255,
        )
    else:
        # A compact, original three-plane Flutter-style chevron. The geometry
        # is intentionally rendered from primitives rather than copied artwork.
        draw.polygon(((50, 150), (116, 84), (151, 119), (85, 185)), fill=255)
        draw.polygon(((85, 185), (151, 119), (204, 172), (138, 238)), fill=255)
        draw.polygon(((138, 238), (169, 207), (204, 238), (169, 273)), fill=255)

    return mask.point(lambda value: 255 if value >= 64 else 0, mode="1")


def mask_for_stage(stage: str) -> Image.Image:
    return portrait_mask() if stage == "portrait" else language_mask(stage)


@lru_cache(maxsize=None)
def particle_targets(stage: str) -> tuple[tuple[float, float], ...]:
    """Sample each target mask into the same deterministic particle count."""
    mask = mask_for_stage(stage)
    points = [
        (float(x), float(y))
        for y in range(mask.height)
        for x in range(mask.width)
        if mask.getpixel((x, y))
    ]
    if not points:
        raise ValueError(f"Particle target {stage!r} contains no visible pixels")

    seeds = {
        "portrait": 2026082601,
        "csharp": 2026082602,
        "flutter": 2026082603,
        "cplusplus": 2026082604,
    }
    generator = random.Random(seeds[stage])
    if len(points) >= PARTICLE_COUNT:
        return tuple(generator.sample(points, PARTICLE_COUNT))

    expanded: list[tuple[float, float]] = []
    for index in range(PARTICLE_COUNT):
        x, y = points[index % len(points)]
        # Repeated target points fan out only slightly, retaining crisp glyphs.
        expanded.append(
            (x + generator.uniform(-1.15, 1.15), y + generator.uniform(-1.15, 1.15))
        )
    generator.shuffle(expanded)
    return tuple(expanded)


@lru_cache(maxsize=1)
def particle_drifts() -> tuple[tuple[float, float], ...]:
    """Stable outward vectors used only during the middle of a morph."""
    generator = random.Random(2026082605)
    drifts = []
    for _ in range(PARTICLE_COUNT):
        angle = generator.uniform(0, math.tau)
        distance = generator.uniform(14, 34)
        drifts.append((math.cos(angle) * distance, math.sin(angle) * distance))
    return tuple(drifts)


def stage_color(theme: dict[str, str], stage: str) -> tuple[int, int, int]:
    value = {
        "portrait": theme["portrait"],
        "csharp": theme["portrait"],
        "flutter": theme["ui"],
        "cplusplus": theme["accent"],
    }[stage]
    return hex_to_rgb(value)


def draw_map_corners(draw: ImageDraw.ImageDraw, theme: dict[str, str]) -> None:
    """Frame the animation without placing labels or cards over the portrait."""
    left, top, right, bottom = MAP_BOUNDS
    color = blend_rgb(hex_to_rgb(theme["ui"]), hex_to_rgb(theme["panel"]), 0.9)
    length = 19
    for points in (
        ((left, top + length), (left, top), (left + length, top)),
        ((right - length, top), (right, top), (right, top + length)),
        ((left, bottom - length), (left, bottom), (left + length, bottom)),
        ((right - length, bottom), (right, bottom), (right, bottom - length)),
    ):
        draw.line(points, fill=color, width=2)


def draw_particle_morph(
    draw: ImageDraw.ImageDraw, theme: dict[str, str], elapsed: float
) -> None:
    """Render the portrait/language sequence as particles, never as an overlay."""
    source, target, progress = morph_state(elapsed)
    eased = ramp(progress)
    scatter = math.sin(math.pi * progress)
    source_points = particle_targets(source)
    target_points = particle_targets(target)
    drifts = particle_drifts()
    origin_x, origin_y = PORTRAIT_POSITION
    left, top, right, bottom = MAP_BOUNDS
    panel_color = hex_to_rgb(theme["panel"])
    particle_color = lerp_rgb(stage_color(theme, source), stage_color(theme, target), eased)
    bright = blend_rgb(particle_color, panel_color, 0.95)
    regular = blend_rgb(particle_color, panel_color, 0.82)
    soft = blend_rgb(particle_color, panel_color, 0.62)

    for index, ((source_x, source_y), (target_x, target_y), (drift_x, drift_y)) in enumerate(
        zip(source_points, target_points, drifts)
    ):
        shimmer = math.sin(elapsed * 6.2 + index * 0.711) * 0.72
        x = origin_x + source_x + (target_x - source_x) * eased + drift_x * scatter + shimmer
        y = origin_y + source_y + (target_y - source_y) * eased + drift_y * scatter + shimmer * 0.45
        x = min(right - 1, max(left + 1, x))
        y = min(bottom - 1, max(top + 1, y))
        point = (round(x), round(y))
        if index % 17 == 0:
            draw.ellipse(
                (point[0] - 1, point[1] - 1, point[0] + 1, point[1] + 1),
                fill=bright,
            )
        elif index % 5 == 0:
            draw.point(point, fill=regular)
        else:
            draw.point(point, fill=soft)


def leader(label: str) -> str:
    return f"{label} {'.' * max(4, 22 - len(label))}"


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


def render_svg(theme_name: str) -> str:
    theme = THEMES[theme_name]
    rows = "\n      ".join(
        row_svg(index, label, value, theme)
        for index, (label, value) in enumerate(ROWS)
    )
    portrait = portrait_paths()
    title = f"Renan Augusto - {theme_name} technical profile"
    desc = (
        "Static accessible terminal profile. The Visual Map contains only an "
        "identity-preserving portrait traced as one-bit particle paths; the "
        "animated version morphs it into C#, Flutter and C++ particle glyphs. "
        "Only verified public profile facts are included."
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
  <path d="M74 160H461" stroke="{theme["border"]}" stroke-width="1"/>

  <path d="M95 188V169H114 M421 169H440V188 M95 487V506H114 M421 506H440V487" fill="none" stroke="{theme["ui"]}" stroke-opacity=".9" stroke-width="2"/>
  <g fill="{theme["portrait"]}">{portrait}</g>

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
    intro_progress = min(1.0, elapsed / INTRO_SECONDS)
    active_row = active_system_row(elapsed)
    image = Image.new("RGB", (WIDTH, HEIGHT), hex_to_rgb(theme["background"]))
    draw = ImageDraw.Draw(image)
    mono12 = get_font(12)
    mono13 = get_font(13)
    mono14 = get_font(14)
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
    draw.line((74, 160, 461, 160), fill=hex_to_rgb(theme["border"]), width=1)
    draw.text((526, 130), "SYSTEM.INFO", font=mono17, fill=hex_to_rgb(theme["ui"]))
    if elapsed < INTRO_SECONDS:
        header_text = f"BOOT SEQUENCE / {round(intro_progress * 100):03d}%"
    else:
        header_text = f"LIVE SCAN / {active_row + 1:02d}/{len(ROWS):02d}"
    header_box = draw.textbbox((0, 0), header_text, font=mono12)
    draw.text((1110 - (header_box[2] - header_box[0]), 133), header_text, font=mono12, fill=hex_to_rgb(theme["muted"]))
    draw.line((526, 160, 1110, 160), fill=hex_to_rgb(theme["border"]), width=1)

    # The entire left area is reserved for the particle transformation; nothing
    # is drawn over the portrait or language glyphs.
    draw_map_corners(draw, theme)
    draw_particle_morph(draw, theme, elapsed)

    # System fields: an accessibility-safe boot reveal followed by a live scan.
    # Values never disappear, so the first GIF frame remains self-contained.
    panel_color = hex_to_rgb(theme["panel"])
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
