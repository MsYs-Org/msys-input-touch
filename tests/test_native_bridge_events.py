from __future__ import annotations

from pathlib import Path
import unittest

from msys_input_touch.native_bridge import parse_native_event


ROOT = Path(__file__).resolve().parents[1]


class NativeBridgeEventTests(unittest.TestCase):
    def test_move_event_is_typed_and_bounded(self) -> None:
        self.assertEqual(
            parse_native_event({"type": "move", "x": 7, "y": 91}),
            ("move", (7, 91)),
        )
        self.assertIsNone(parse_native_event({"type": "move", "x": True, "y": 2}))
        self.assertIsNone(parse_native_event({"type": "move", "x": 99999, "y": 2}))
        self.assertEqual(
            parse_native_event({"type": "token", "token": "candidate:31"}),
            ("token", "candidate:31"),
        )

    def test_native_header_moves_one_surface_and_python_updates_panel_bounds(self) -> None:
        native = (ROOT / "native/main.c").read_text(encoding="utf-8")
        bridge = (
            ROOT / "files/app/msys_input_touch/native_bridge.py"
        ).read_text(encoding="utf-8")
        self.assertIn("header_drag_event_cb", native)
        self.assertIn("msys_ui_surface_set_geometry", native)
        self.assertIn("emit_move(x, y)", native)
        self.assertIn('elif kind == "move"', bridge)
        self.assertIn("panel = PanelBounds(x, y", bridge)


if __name__ == "__main__":
    unittest.main()
