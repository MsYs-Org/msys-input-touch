from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

from msys_input_touch.x11_input import (
    InputBackendError,
    UnavailableBackend,
    XdotoolBackend,
    create_backend,
    keysym_for_key,
    xdotool_key_name,
)


class X11InputAdapterTests(unittest.TestCase):
    def test_ascii_and_required_controls_have_bounded_keysyms(self) -> None:
        self.assertEqual(keysym_for_key("a"), ord("a"))
        self.assertEqual(keysym_for_key("!"), ord("!"))
        self.assertEqual(keysym_for_key("BackSpace"), 0xFF08)
        self.assertEqual(keysym_for_key("Return"), 0xFF0D)
        self.assertEqual(keysym_for_key("Control_L"), 0xFFE3)
        with self.assertRaises(InputBackendError):
            keysym_for_key("你好")

    def test_xdotool_names_are_fixed_key_tokens(self) -> None:
        self.assertEqual(xdotool_key_name("!"), "exclam")
        self.assertEqual(xdotool_key_name("["), "bracketleft")
        self.assertEqual(xdotool_key_name("space"), "space")
        with self.assertRaises(InputBackendError):
            xdotool_key_name("a; rm -rf /")

    def test_xdotool_uses_argv_without_a_shell(self) -> None:
        backend = XdotoolBackend(sys.executable)
        completed = mock.Mock(returncode=0, stdout="42\n", stderr="")
        with mock.patch("msys_input_touch.x11_input.subprocess.run", return_value=completed) as run:
            self.assertEqual(backend.focused_window(), 42)
            backend.send_key("v", ("Control_L",))
        first = run.call_args_list[0]
        second = run.call_args_list[1]
        self.assertEqual(first.args[0][1:], ["getwindowfocus"])
        self.assertEqual(second.args[0][1:], ["key", "--clearmodifiers", "ctrl+v"])
        self.assertNotIn("shell", first.kwargs)
        self.assertNotIn("shell", second.kwargs)

    def test_backend_selection_prefers_xtest_then_safe_fallback(self) -> None:
        xtest = object()
        xdotool = object()
        self.assertIs(
            create_backend(xtest_factory=lambda: xtest, xdotool_factory=lambda: xdotool),
            xtest,
        )

        def missing():
            raise InputBackendError("missing")

        self.assertIs(
            create_backend(xtest_factory=missing, xdotool_factory=lambda: xdotool),
            xdotool,
        )
        unavailable = create_backend(xtest_factory=missing, xdotool_factory=missing)
        self.assertIsInstance(unavailable, UnavailableBackend)
        self.assertFalse(unavailable.available)

    def test_adapter_source_has_no_shell_or_raw_focus_mutation(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "files"
            / "app"
            / "msys_input_touch"
            / "x11_input.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("XSetInputFocus", source)
        # XGetInputFocus can return a toolkit child for Qt, Tk or Chromium.
        # The XTest path must normalize it to the catalogued top-level XID.
        self.assertIn("XQueryTree", source)
        self.assertIn("parent.value == root.value", source)


if __name__ == "__main__":
    unittest.main()
