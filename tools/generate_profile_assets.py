"""Generate sharp, self-contained SVG particle animations for the profile.

The portrait and language targets are generated locally from raster masks, but
the published assets contain only SVG geometry. Motion uses declarative SMIL:
every moving particle is a local ``<use>`` of a one-pixel path and moves across
the portrait, C#, Flutter and C++ targets in one seamless loop.
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
ANIMATION_SECONDS = 14.2
PORTRAIT_CROP = (172, 0, 1012, 1050)
PORTRAIT_SIZE = (256, 320)
PORTRAIT_POSITION = (139, 174)
MAP_BOUNDS = (95, 169, 440, 506)
SVG_PARTICLE_COUNT = 1_150

# The repeated first and final portrait positions make the loop start on a
# complete, readable image rather than a blank animation frame.
MORPH_KEY_TIMES = (
    0.000,
    0.170,
    0.225,
    0.285,
    0.395,
    0.455,
    0.515,
    0.625,
    0.685,
    0.745,
    0.855,
    0.915,
    0.970,
    1.000,
)
MORPH_SPLINES = ";".join(".42 0 .18 1" for _ in range(len(MORPH_KEY_TIMES) - 1))
MORPH_OPACITY = ".96;.96;.24;.96;.96;.24;.96;.96;.24;.96;.96;.24;.96;.96"

ROWS: tuple[tuple[str, str], ...] = (
    ("SUBJECT", "Renan Augusto"),
    ("ROLE", "Software Engineer"),
    ("FOCUS", "Game Dev / Embedded"),
    ("STATUS", "Building"),
    ("TOOLCHAIN", "Unity / Unreal"),
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
        "flutter_light": "#54C5F8",
        "flutter_mid": "#29B6F6",
        "flutter_dark": "#0D5F9E",
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
        "flutter_light": "#0288D1",
        "flutter_mid": "#039BE5",
        "flutter_dark": "#01579B",
    },
}


def leader(label: str) -> str:
    return f"{label} {'.' * max(4, 22 - len(label))}"


def svg_row_y(index: int) -> float:
    return 183 + index * 34.0


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


@lru_cache(maxsize=1)
def portrait_mask() -> Image.Image:
    """Return the identity-preserving portrait as a one-bit dither mask."""
    if not PORTRAIT_REFERENCE.exists():
        raise FileNotFoundError(
            f"Missing portrait reference: {PORTRAIT_REFERENCE.relative_to(ROOT)}"
        )
    source = Image.open(PORTRAIT_REFERENCE).convert("L")
    portrait = source.crop(PORTRAIT_CROP).resize(PORTRAIT_SIZE, Image.Resampling.LANCZOS)
    return portrait.point(lambda value: 255 if value >= 90 else 0, mode="1")


def flutter_point(x: float, y: float) -> tuple[int, int]:
    """Map an original 202px Flutter artboard into the local particle canvas."""
    size = 240.0
    artboard = 202.0
    inset = 18.0
    scale = size / artboard
    return (
        round((PORTRAIT_SIZE[0] - size) / 2 + (inset + x) * scale),
        round((PORTRAIT_SIZE[1] - size) / 2 + y * scale),
    )


def flutter_polygon(*points: tuple[float, float]) -> list[tuple[int, int]]:
    return [flutter_point(x, y) for x, y in points]


FLUTTER_LIGHT_SHARDS = (
    ((37.7, 128.9), (9.8, 101.0), (100.4, 10.4), (156.2, 10.4)),
    ((156.2, 94.0), (100.4, 94.0), (78.5, 115.9), (106.4, 143.8)),
)
FLUTTER_MID_SHARD = ((51.6, 142.8), (79.5, 115.1), (107.4, 142.8), (79.5, 170.7))
FLUTTER_DARK_SHARD = ((79.5, 170.7), (100.4, 191.6), (156.2, 191.6), (107.4, 142.8))


@lru_cache(maxsize=1)
def flutter_plane_masks() -> tuple[Image.Image, Image.Image, Image.Image]:
    """Create separate Flutter planes so the mark reads clearly at 1-bit scale."""
    light = Image.new("1", PORTRAIT_SIZE, 0)
    middle = Image.new("1", PORTRAIT_SIZE, 0)
    dark = Image.new("1", PORTRAIT_SIZE, 0)
    light_draw = ImageDraw.Draw(light)
    for shard in FLUTTER_LIGHT_SHARDS:
        light_draw.polygon(flutter_polygon(*shard), fill=255)
    ImageDraw.Draw(middle).polygon(flutter_polygon(*FLUTTER_MID_SHARD), fill=255)
    ImageDraw.Draw(dark).polygon(flutter_polygon(*FLUTTER_DARK_SHARD), fill=255)
    return light, middle, dark


@lru_cache(maxsize=None)
def language_mask(stage: str) -> Image.Image:
    """Build local, geometric language targets without external logo assets."""
    if stage not in {"csharp", "flutter", "cplusplus"}:
        raise ValueError(f"Unsupported language target: {stage}")

    if stage == "flutter":
        combined = Image.new("1", PORTRAIT_SIZE, 0)
        for plane in flutter_plane_masks():
            combined.paste(plane, mask=plane)
        return combined

    mask = Image.new("L", PORTRAIT_SIZE, 0)
    draw = ImageDraw.Draw(mask)
    center = (PORTRAIT_SIZE[0] // 2, PORTRAIT_SIZE[1] // 2)
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
    box = draw.textbbox((0, 0), glyph, font=font, stroke_width=1)
    draw.text(
        (
            center[0] - (box[2] - box[0]) / 2,
            center[1] - (box[3] - box[1]) / 2 - 4,
        ),
        glyph,
        font=font,
        fill=255,
        stroke_width=1,
        stroke_fill=255,
    )
    return mask.point(lambda value: 255 if value >= 64 else 0, mode="1")


def mask_edge(mask: Image.Image, x: int, y: int) -> bool:
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nx, ny = x + dx, y + dy
        if nx < 0 or ny < 0 or nx >= mask.width or ny >= mask.height:
            return True
        if not mask.getpixel((nx, ny)):
            return True
    return False


def stipple_mask(mask: Image.Image, seed: int) -> Image.Image:
    """Turn solid glyph masks into dense, crisp one-pixel particle fields."""
    stippled = Image.new("1", mask.size, 0)
    for y in range(mask.height):
        for x in range(mask.width):
            if not mask.getpixel((x, y)):
                continue
            value = (x * 73_856_093 ^ y * 19_349_663 ^ seed * 83_492_791) & 0xFFFFFFFF
            value ^= value >> 13
            density = 92 if mask_edge(mask, x, y) else 58
            if value % 100 < density:
                stippled.putpixel((x, y), 255)
    return stippled


@lru_cache(maxsize=None)
def stage_mask(stage: str) -> Image.Image:
    if stage == "portrait":
        return portrait_mask()
    seeds = {"csharp": 11, "flutter": 17, "cplusplus": 23}
    return stipple_mask(language_mask(stage), seeds[stage])


@lru_cache(maxsize=None)
def flutter_plane_path_data() -> tuple[str, str, str]:
    return tuple(
        mask_path_data(stipple_mask(mask, 31 + index * 7), PORTRAIT_POSITION)
        for index, mask in enumerate(flutter_plane_masks())
    )


def mask_path_data(mask: Image.Image, origin: tuple[int, int]) -> str:
    """Compress a one-bit particle mask into compact SVG path runs."""
    x_origin, y_origin = origin
    runs: list[str] = []
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
            runs.append(f"M{x_origin + start} {y_origin + y}h{length}v1h-{length}z")
    return "".join(runs)


@lru_cache(maxsize=None)
def stage_path_data(stage: str) -> str:
    return mask_path_data(stage_mask(stage), PORTRAIT_POSITION)


@lru_cache(maxsize=None)
def stage_points(stage: str) -> tuple[tuple[int, int], ...]:
    """Return a stable particle sample for morphing between all four targets."""
    mask = stage_mask(stage)
    candidates = [
        (x, y)
        for y in range(mask.height)
        for x in range(mask.width)
        if mask.getpixel((x, y))
    ]
    if not candidates:
        raise ValueError(f"Particle target {stage!r} contains no visible pixels")
    seed = {"portrait": 101, "csharp": 103, "flutter": 107, "cplusplus": 109}[stage]
    generator = random.Random(seed)
    if len(candidates) >= SVG_PARTICLE_COUNT:
        return tuple(generator.sample(candidates, SVG_PARTICLE_COUNT))
    return tuple(candidates[index % len(candidates)] for index in range(SVG_PARTICLE_COUNT))


@lru_cache(maxsize=1)
def motion_drifts() -> tuple[tuple[int, int], ...]:
    generator = random.Random(113)
    drifts = []
    for _ in range(SVG_PARTICLE_COUNT):
        angle = generator.uniform(0, math.tau)
        distance = generator.uniform(16, 36)
        drifts.append((round(math.cos(angle) * distance), round(math.sin(angle) * distance)))
    return tuple(drifts)


def absolute_point(point: tuple[int, int]) -> tuple[int, int]:
    return PORTRAIT_POSITION[0] + point[0], PORTRAIT_POSITION[1] + point[1]


def scatter_point(
    first: tuple[int, int], second: tuple[int, int], drift: tuple[int, int]
) -> tuple[int, int]:
    left, top, right, bottom = MAP_BOUNDS
    x = round((first[0] + second[0]) / 2 + drift[0])
    y = round((first[1] + second[1]) / 2 + drift[1])
    return min(right - 1, max(left + 1, x)), min(bottom - 1, max(top + 1, y))


@lru_cache(maxsize=1)
def animated_particle_uses() -> str:
    """Build original SMIL movement for the reusable particle primitive."""
    targets = {
        stage: stage_points(stage)
        for stage in ("portrait", "csharp", "flutter", "cplusplus")
    }
    drifts = motion_drifts()
    key_times = ";".join(f"{value:.3f}" for value in MORPH_KEY_TIMES)
    uses: list[str] = []

    for index in range(SVG_PARTICLE_COUNT):
        portrait = absolute_point(targets["portrait"][index])
        csharp = absolute_point(targets["csharp"][index])
        flutter = absolute_point(targets["flutter"][index])
        cplusplus = absolute_point(targets["cplusplus"][index])
        drift = drifts[index]
        frames = (
            portrait,
            portrait,
            scatter_point(portrait, csharp, drift),
            csharp,
            csharp,
            scatter_point(csharp, flutter, drift),
            flutter,
            flutter,
            scatter_point(flutter, cplusplus, drift),
            cplusplus,
            cplusplus,
            scatter_point(cplusplus, portrait, drift),
            portrait,
            portrait,
        )
        values = ";".join(f"{x} {y}" for x, y in frames)
        dot = "#particle-dot-large" if index % 13 == 0 else "#particle-dot"
        uses.append(
            f'<use href="{dot}" transform="translate({portrait[0]} {portrait[1]})">'
            f'<animateTransform attributeName="transform" type="translate" '
            f'values="{values}" keyTimes="{key_times}" dur="{ANIMATION_SECONDS}s" '
            f'repeatCount="indefinite" calcMode="spline" keySplines="{MORPH_SPLINES}"/>'
            f'<animate attributeName="opacity" values="{MORPH_OPACITY}" '
            f'keyTimes="{key_times}" dur="{ANIMATION_SECONDS}s" repeatCount="indefinite"/>'
            "</use>"
        )
    return "\n        ".join(uses)


def stage_opacity(stage: str) -> str:
    values = {
        "portrait": (1, 1, 0.28, 0, 0, 0, 0, 0, 0, 0, 0, 0.28, 1, 1),
        "csharp": (0, 0, 0.22, 1, 1, 0.22, 0, 0, 0, 0, 0, 0, 0, 0),
        "flutter": (0, 0, 0, 0, 0, 0.22, 1, 1, 0.22, 0, 0, 0, 0, 0),
        "cplusplus": (0, 0, 0, 0, 0, 0, 0, 0, 0.22, 1, 1, 0.22, 0, 0),
    }[stage]
    return ";".join(str(value) for value in values)


def state_group(stage: str, theme: dict[str, str]) -> str:
    key_times = ";".join(f"{value:.3f}" for value in MORPH_KEY_TIMES)
    if stage == "flutter":
        light, middle, dark = flutter_plane_path_data()
        content = (
            f'<path d="{light}" fill="{theme["flutter_light"]}"/>\n'
            f'        <path d="{middle}" fill="{theme["flutter_mid"]}"/>\n'
            f'        <path d="{dark}" fill="{theme["flutter_dark"]}"/>'
        )
    else:
        content = f'<path d="{stage_path_data(stage)}"/>'
    return (
        f'<g id="particle-{stage}" opacity="0">\n'
        f'        <animate attributeName="opacity" values="{stage_opacity(stage)}" '
        f'keyTimes="{key_times}" dur="{ANIMATION_SECONDS}s" repeatCount="indefinite"/>\n'
        f'        {content}\n'
        "      </g>"
    )


def row_svg(index: int, label: str, value: str, theme: dict[str, str]) -> str:
    y = svg_row_y(index)
    label_color = theme["accent"] if label.startswith("CORE.") else (
        theme["ui"] if label.startswith("GRID.") else theme["muted"]
    )
    value_length = max(74, min(302, round(len(value) * 8.45)))
    delay = 0.42 + index * 0.11
    return (
        f'<g opacity="0">\n'
        f'        <animate attributeName="opacity" values="0;1" dur=".34s" begin="{delay:.2f}s" fill="freeze"/>\n'
        f'        <animateTransform attributeName="transform" type="translate" values="-8 0;0 0" dur=".34s" begin="{delay:.2f}s" fill="freeze"/>\n'
        f'        <text x="526" y="{y:.1f}" fill="{label_color}" font-size="14" '
        f'textLength="246" lengthAdjust="spacing">{escape(leader(label))}</text>\n'
        f'        <text x="790" y="{y:.1f}" fill="{theme["text"]}" font-size="14" '
        f'textLength="{value_length}" lengthAdjust="spacing">{escape(value)}</text>\n'
        "      </g>"
    )


def render_svg(theme_name: str) -> str:
    theme = THEMES[theme_name]
    rows = "\n      ".join(
        row_svg(index, label, value, theme)
        for index, (label, value) in enumerate(ROWS)
    )
    states = "\n      ".join(
        state_group(stage, theme)
        for stage in ("portrait", "csharp", "flutter", "cplusplus")
    )
    moving_particles = animated_particle_uses()
    title = f"Renan Augusto - {theme_name} animated technical profile"
    desc = (
        "Animated terminal profile. A sharp, identity-preserving particle portrait "
        "transforms into C#, Flutter and C++ symbols, while verified system details "
        "appear in the adjacent panel."
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
    <linearGradient id="particle-gradient" x1="0" y1="0" x2="0" y2="1" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{theme["ui"]}"/>
      <stop offset=".46" stop-color="{theme["portrait"]}"/>
      <stop offset="1" stop-color="{theme["accent"]}"/>
      <animateTransform attributeName="gradientTransform" type="translate" values="0 -80;0 80;0 -80" dur="9s" repeatCount="indefinite"/>
    </linearGradient>
    <path id="particle-dot" d="M0 0h1.2v1.2h-1.2z"/>
    <path id="particle-dot-large" d="M-.4-.4h2v2h-2z"/>
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
  <circle cx="947" cy="52.5" r="4" fill="{theme["accent"]}"><animate attributeName="opacity" values="1;.28;1" dur="1.5s" repeatCount="indefinite"/></circle>
  <text x="962" y="57" fill="{theme["text"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="13" font-weight="700">@RenanAugustoKwn</text>

  <rect x="49" y="110" width="437" height="420" rx="15" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="1.5"/>
  <text x="74" y="145" fill="{theme["ui"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="17" font-weight="700" letter-spacing="1.4">VISUAL.MAP</text>
  <path d="M74 160H461" stroke="{theme["border"]}" stroke-width="1"/>
  <path d="M95 188V169H114 M421 169H440V188 M95 487V506H114 M421 506H440V487" fill="none" stroke="{theme["ui"]}" stroke-width="2" stroke-opacity=".82">
    <animate attributeName="stroke-opacity" values=".55;1;.55" dur="2.4s" repeatCount="indefinite"/>
  </path>
  <g fill="url(#particle-gradient)" shape-rendering="crispEdges">
      {states}
      <g id="moving-particles">
        {moving_particles}
      </g>
  </g>

  <rect x="512" y="110" width="620" height="420" rx="15" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="1.5"/>
  <text x="526" y="145" fill="{theme["ui"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="17" font-weight="700" letter-spacing="1.4">SYSTEM.INFO</text>
  <text x="1110" y="145" text-anchor="end" fill="{theme["accent"]}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="12" font-weight="700">● LIVE<animate attributeName="opacity" values="1;.28;1" dur="1.6s" repeatCount="indefinite"/></text>
  <path d="M526 160H1110" stroke="{theme["border"]}" stroke-width="1"/>
  <g opacity="0">
    <animate attributeName="opacity" values="0;.20;0" keyTimes="0;.15;1" dur="5.8s" repeatCount="indefinite"/>
    <rect x="520" y="171" width="602" height="22" rx="5" fill="{theme["ui"]}"/>
    <animateTransform attributeName="transform" type="translate" values="0 0;0 306;0 0" dur="5.8s" repeatCount="indefinite"/>
  </g>
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


def main() -> None:
    for theme_name in THEMES:
        (ROOT / f"{theme_name}.svg").write_text(
            render_svg(theme_name), encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    main()
