from __future__ import annotations

import unittest

from msys_input_touch.geometry import clamp_panel_position, keyboard_geometry


class KeyboardGeometryTests(unittest.TestCase):
    def test_mobile_keyboard_fits_above_navigation(self) -> None:
        geometry = keyboard_geometry(320, 480, bottom_inset=42)
        self.assertEqual(geometry.width, 312)
        self.assertLessEqual(geometry.y + geometry.height, 438)
        self.assertGreaterEqual(geometry.height, 190)

    def test_landscape_desktop_and_tiny_screens_remain_bounded(self) -> None:
        for width, height in ((480, 320), (1920, 1080), (40, 30), (1, 1)):
            with self.subTest(size=(width, height)):
                geometry = keyboard_geometry(width, height)
                self.assertTrue(1 <= geometry.width <= width)
                self.assertTrue(1 <= geometry.height <= height)
                self.assertTrue(0 <= geometry.x <= width - geometry.width)
                self.assertTrue(0 <= geometry.y <= height - geometry.height)
        self.assertGreaterEqual(keyboard_geometry(480, 320).height, 180)

    def test_drag_is_clamped_to_live_screen(self) -> None:
        self.assertEqual(clamp_panel_position(-20, 999, 300, 200, 320, 480), (0, 280))
        self.assertEqual(clamp_panel_position(10, 20, 300, 200, 320, 480), (10, 20))


if __name__ == "__main__":
    unittest.main()
