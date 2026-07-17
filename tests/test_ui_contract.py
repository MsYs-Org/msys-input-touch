from __future__ import annotations

import ast
from collections import deque
from pathlib import Path
import unittest
from unittest import mock

from msys_input_touch.model import KeyboardModel
from msys_input_touch.pinyin import PinyinDictionary
from msys_input_touch.ui import TouchKeyboardView


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "files" / "app" / "msys_input_touch"


class TouchUiContractTests(unittest.TestCase):
    def test_every_tk_window_receives_manifest_identity_at_creation(self) -> None:
        constructors = []
        violations = []
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            identity_names = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = node.value
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if value is not None and "MSYS_WINDOW_IDENTITY" in ast.unparse(value):
                        identity_names.update(
                            item.id for item in targets if isinstance(item, ast.Name)
                        )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {"Tk", "Toplevel"}:
                    continue
                constructors.append((path.name, node.lineno, node.func.attr))
                keyword_name = "className" if node.func.attr == "Tk" else "class_"
                value = next(
                    (item.value for item in node.keywords if item.arg == keyword_name),
                    None,
                )
                if value is None or not (
                    "MSYS_WINDOW_IDENTITY" in ast.unparse(value)
                    or isinstance(value, ast.Name) and value.id in identity_names
                    or isinstance(value, ast.Attribute) and value.attr == "identity"
                ):
                    violations.append(f"{path.name}:{node.lineno}:{node.func.attr}")
        self.assertTrue(constructors)
        self.assertFalse(violations, str(violations))

    def test_ui_does_not_grab_or_force_focus_and_uses_timer_motion(self) -> None:
        source = (PACKAGE / "ui.py").read_text(encoding="utf-8")
        self.assertNotIn("grab_set", source)
        self.assertNotIn("focus_force", source)
        self.assertNotIn("time.sleep", source)
        self.assertIn("overrideredirect(True)", source)
        self.assertIn('name="keyboard"', source)
        self.assertIn('attributes("-type", "dock")', source)
        self.assertIn("root.after(18", source)
        self.assertIn("root.after(16", source)
        self.assertIn("bind_tk_text_wrap", source)
        self.assertNotIn('attributes("-alpha"', source)
        self.assertIn("configure_tk_window_identity", source)

    def test_repo_has_no_external_input_framework_dependency(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in [
                ROOT / "manifest.json",
                ROOT / "pyproject.toml",
                *sorted(PACKAGE.glob("*.py")),
            ]
        ).lower()
        for forbidden in ("import dbus", "import ibus", "import fcitx", "pyside", "pyqt"):
            self.assertNotIn(forbidden, combined)

    def test_character_actions_request_only_their_required_damage(self) -> None:
        dictionary = PinyinDictionary.from_mapping({
            "schema": "msys.pinyin-dictionary.v1",
            "entries": {"ni": ["你", "呢"]},
        })

        def view_for(mode: str) -> TouchKeyboardView:
            view = TouchKeyboardView.__new__(TouchKeyboardView)
            view.model = KeyboardModel(dictionary, mode)
            view.pending = deque(maxlen=64)
            view._render = mock.Mock()
            view._start_next_job = mock.Mock()
            return view

        english = view_for("en")
        english_layout = english.model.layout()
        english._handle_token("char:a")
        self.assertEqual(english.model.layout(), english_layout)
        self.assertEqual(english.pending[0].value, "a")
        english._render.assert_not_called()

        chinese = view_for("zh")
        chinese_layout = chinese.model.layout()
        chinese._handle_token("char:n")
        self.assertEqual(chinese.model.layout(), chinese_layout)
        self.assertEqual(chinese.model.composition, "n")
        self.assertFalse(chinese.pending)
        chinese._render.assert_called_once_with()

    def test_key_refresh_keeps_stable_widget_subtrees(self) -> None:
        source = (PACKAGE / "ui.py").read_text(encoding="utf-8")
        self.assertIn("layout_signature != self._rendered_layout", source)
        self.assertIn("candidates != self._rendered_candidates", source)
        self.assertEqual(source.count("child.destroy()"), 2)
        self.assertIn("if self.status_var.get() != value", source)
        self.assertIn("widget.configure(bg=pressed)", source)
        self.assertIn("widget.configure(bg=normal)", source)
        self.assertNotIn("tk.Canvas(", source)
        self.assertNotIn('.delete("all")', source)

    def test_hidden_panel_can_be_prepared_without_mapping(self) -> None:
        view = TouchKeyboardView.__new__(TouchKeyboardView)
        view.panel = None
        view._build_panel = mock.Mock()
        self.assertFalse(view.prepared)
        view.prepare()
        view._build_panel.assert_called_once_with()

    def test_startup_overlaps_focus_probe_and_panel_build_with_role_readiness(self) -> None:
        source = (PACKAGE / "service.py").read_text(encoding="utf-8")
        run_body = source.split("def run(", 1)[1]
        supervised = source.split("if not standalone:", 1)[1]
        self.assertLess(
            run_body.index("\n        request_capture()"),
            run_body.index("import tkinter as tk"),
        )
        self.assertLess(
            supervised.index("client.ready()"),
            supervised.index("root.after_idle(view.prepare)"),
        )
        self.assertIn("input-method: first-map", source)
        self.assertIn("show_to_map_ms=", source)
        self.assertIn("startup_ms=", source)

    def test_lvgl_candidates_come_only_from_the_bounded_pinyin_model(self) -> None:
        bridge = (PACKAGE / "native_bridge.py").read_text(encoding="utf-8")
        native = (ROOT / "native/main.c").read_text(encoding="utf-8")
        self.assertIn('"candidates": list(model.candidates[:32])', bridge)
        self.assertIn('msys_mipc_json_get_raw(json, "candidates"', native)
        self.assertNotIn("fake_candidate", bridge.lower())
        self.assertNotIn("fake_candidate", native.lower())


if __name__ == "__main__":
    unittest.main()
