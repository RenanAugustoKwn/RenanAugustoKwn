from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageChops
from tools import generate_profile_assets as profile_assets


ROOT = Path(__file__).resolve().parents[1]
SVG_NAMES = ("dark.svg", "light.svg")
GIF_NAMES = ("visual-map-dark.gif", "visual-map-light.gif")
REQUIRED_ROWS = (
    "SUBJECT",
    "ROLE",
    "FOCUS",
    "STATUS",
    "TOOLCHAIN",
    "CORE.ENGINE",
    "CORE.HARDWARE",
    "GRID.MAIL",
    "GRID.LINKEDIN",
    "GRID.GITHUB",
)
FORBIDDEN_MAP_COPY = (
    "SOFTWARE",
    "GAME DEV",
    "EMBEDDED",
    "AUTOMATION",
    "CORE SIGNAL",
    "MAP BOOT",
    "ACTIVE ROUTE",
    "4 LINKED DISCIPLINES",
    "STATIC CORE + ANIMATED PULSE",
)
FORBIDDEN_TAGS = {
    "animate",
    "animateMotion",
    "animateTransform",
    "foreignObject",
    "image",
    "script",
    "set",
    "style",
    "use",
}
STYLE_ATTRIBUTES = {
    "fill",
    "stroke",
    "stop-color",
    "stop-opacity",
    "opacity",
    "stroke-opacity",
}


def local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def geometry_signature(path: Path) -> tuple[tuple[str, tuple[tuple[str, str], ...], str], ...]:
    root = ET.parse(path).getroot()
    signature = []
    for element in root.iter():
        tag = local_name(element.tag)
        attributes = tuple(
            sorted(
                (local_name(key), value)
                for key, value in element.attrib.items()
                if local_name(key) not in STYLE_ATTRIBUTES
            )
        )
        text = "" if tag == "title" else (element.text or "").strip()
        signature.append((tag, attributes, text))
    return tuple(signature)


class ProfileAssetTests(unittest.TestCase):
    def test_static_svgs_are_safe_accessible_and_complete(self) -> None:
        for name in SVG_NAMES:
            root = ET.parse(ROOT / name).getroot()
            self.assertEqual(root.attrib["width"], "1180")
            self.assertEqual(root.attrib["height"], "610")
            self.assertEqual(root.attrib["viewBox"], "0 0 1180 610")
            self.assertEqual(root.attrib["role"], "img")
            self.assertEqual(root.attrib["aria-labelledby"], "title desc")

            elements = tuple(root.iter())
            tags = {local_name(element.tag) for element in elements}
            self.assertIn("title", tags)
            self.assertIn("desc", tags)
            self.assertFalse(tags & FORBIDDEN_TAGS)
            self.assertGreater(
                sum(local_name(element.tag) == "path" for element in elements),
                1_000,
                "The identity-preserving portrait must be represented by SVG paths.",
            )
            self.assertGreaterEqual(
                sum("textLength" in element.attrib for element in elements),
                len(REQUIRED_ROWS) * 2,
            )
            self.assertGreaterEqual(
                sum("lengthAdjust" in element.attrib for element in elements),
                len(REQUIRED_ROWS) * 2,
            )

            text = " ".join(part.strip() for part in root.itertext() if part.strip())
            for label in REQUIRED_ROWS:
                self.assertIn(label, text)
            self.assertNotIn("not published", text.casefold())
            for forbidden in FORBIDDEN_MAP_COPY:
                self.assertNotIn(forbidden, text)
            for element in elements:
                if local_name(element.tag) != "text":
                    continue
                x = float(element.attrib.get("x", "999"))
                y = float(element.attrib.get("y", "0"))
                self.assertFalse(
                    x < 486 and y >= 160,
                    "The portrait area must not contain text overlays.",
                )
            for element in elements:
                self.assertNotIn("href", {local_name(key) for key in element.attrib})
                for value in element.attrib.values():
                    if "url(" in value.lower():
                        self.assertRegex(value, r"^url\(#[A-Za-z0-9_-]+\)$")
                    self.assertNotIn("data:", value.lower())
                    self.assertNotIn("http://", value.lower())
                    self.assertNotIn("https://", value.lower())

    def test_themes_have_identical_geometry_and_content(self) -> None:
        self.assertEqual(
            geometry_signature(ROOT / "dark.svg"),
            geometry_signature(ROOT / "light.svg"),
        )

    def test_gifs_are_full_size_complete_and_follow_the_design_loop(self) -> None:
        for name in GIF_NAMES:
            with Image.open(ROOT / name) as image:
                self.assertEqual(image.format, "GIF")
                self.assertEqual(image.size, (1180, 610))
                self.assertEqual(image.n_frames, 36)
                durations = []
                for index in range(image.n_frames):
                    image.seek(index)
                    durations.append(image.info["duration"])
                self.assertEqual(sum(durations), 14_200)
                image.seek(0)
                first_frame = image.convert("RGB")
                self.assertGreater(
                    len(first_frame.getcolors(maxcolors=1_000_000) or []),
                    12,
                    "The first GIF frame must contain the complete visual map.",
                )
                image.seek(image.n_frames // 2)
                middle_frame = image.convert("RGB")
                animation_delta = ImageChops.difference(first_frame, middle_frame)
                self.assertIsNotNone(
                    animation_delta.getbbox(),
                    "The animated map must contain a real visual change.",
                )
                self.assertIsNotNone(
                    animation_delta.crop((49, 110, 487, 531)).getbbox(),
                    "VISUAL.MAP must animate independently.",
                )
                self.assertIsNotNone(
                    animation_delta.crop((512, 110, 1133, 531)).getbbox(),
                    "SYSTEM.INFO must animate independently.",
                )

                key_frames = {}
                for index in (0, 9, 15, 21, 29):
                    image.seek(index)
                    key_frames[index] = image.convert("RGB").crop((49, 110, 487, 531))
                for first, second in ((0, 9), (9, 15), (15, 21), (21, 29)):
                    self.assertIsNotNone(
                        ImageChops.difference(key_frames[first], key_frames[second]).getbbox(),
                        "Each particle target must be visibly distinct.",
                    )

    def test_particle_sequence_has_named_targets_and_is_deterministic(self) -> None:
        expected_states = {
            0: "portrait",
            9: "csharp",
            15: "flutter",
            21: "cplusplus",
            29: "portrait",
        }
        for frame_index, expected in expected_states.items():
            source, target, transition = profile_assets.morph_state(
                profile_assets.elapsed_seconds(frame_index)
            )
            self.assertEqual((source, target), (expected, expected))
            self.assertEqual(transition, 0.0)

        first = profile_assets.draw_gif_frame("dark", 15)
        second = profile_assets.draw_gif_frame("dark", 15)
        self.assertEqual(first.tobytes(), second.tobytes())

    def test_readme_prefers_static_assets_when_motion_is_reduced(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        expected_sources = (
            'dark.svg?v=20260826',
            'light.svg?v=20260826',
            'visual-map-dark.gif?v=20260826',
            'visual-map-light.gif?v=20260826',
        )
        positions = [readme.index(source) for source in expected_sources]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("prefers-reduced-motion: reduce", readme)
        self.assertIn("Mapa visual animado de Renan Augusto", readme)


if __name__ == "__main__":
    unittest.main()
