from __future__ import annotations

import unittest

from msys_input_touch.control import InputMethodControl, STATE_SCHEMA


class InputMethodControlTests(unittest.TestCase):
    def test_typed_show_hide_toggle_status_are_safe_objects(self) -> None:
        control = InputMethodControl(mode="en")
        status, event = control.handle("status", {})
        self.assertIsNone(event)
        self.assertEqual(status["schema"], STATE_SCHEMA)
        self.assertFalse(status["visible"])
        self.assertEqual(status["layout"], "letters")
        self.assertEqual(status["locale"], "en-US")

        shown, event = control.handle("show", {"mode": "zh"})
        self.assertTrue(shown["visible"])
        self.assertEqual((shown["mode"], shown["locale"]), ("zh", "zh-CN"))
        self.assertEqual(event.action, "show")
        hidden, event = control.handle("toggle", {})
        self.assertFalse(hidden["visible"])
        self.assertEqual(event.action, "hide")
        self.assertFalse(event.restore_target)
        hidden, event = control.handle("hide", {})
        self.assertFalse(hidden["visible"])
        self.assertFalse(event.restore_target)

    def test_layout_and_runtime_status_are_explicit(self) -> None:
        control = InputMethodControl()
        control.set_runtime_status(
            backend_name="xtest",
            backend_available=True,
            has_focus_target=True,
        )
        result, event = control.handle("set_mode", {"mode": "numeric"})
        self.assertEqual(result["layout"], "numeric")
        self.assertEqual(result["backend"], {"name": "xtest", "available": True})
        self.assertTrue(result["has_focus_target"])
        self.assertEqual(event.action, "mode")

    def test_invalid_calls_do_not_mutate_state(self) -> None:
        control = InputMethodControl(mode="en")
        before = control.snapshot()
        for method, payload in (
            ("show", {"mode": "emoji"}),
            ("status", {"extra": True}),
            ("hide", {"mode": "en"}),
            ("set_mode", {}),
            ("inject", {"text": "not exposed"}),
        ):
            with self.subTest(method=method):
                with self.assertRaises(ValueError):
                    control.handle(method, payload)
                self.assertEqual(control.snapshot(), before)
        with self.assertRaisesRegex(ValueError, "payload must be an object"):
            control.handle("show", None)

    def test_automatic_dismiss_is_coalesced_and_never_restores_stale_focus(self) -> None:
        control = InputMethodControl(mode="zh")
        control.handle("show", {})
        event = control.dismiss(reason="outside-primary-press")
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.action, "hide")
        self.assertEqual(event.reason, "outside-primary-press")
        self.assertFalse(event.restore_target)
        self.assertFalse(control.snapshot()["visible"])
        self.assertIsNone(control.dismiss(reason="duplicate-watcher-sample"))
        # Back can race with the passive touch watcher.  Its idempotent role
        # hide must not reintroduce an old focus restore after the watcher won.
        _result, repeated_hide = control.handle("hide", {})
        self.assertFalse(repeated_hide.restore_target)
        self.assertEqual(repeated_hide.reason, "outside-primary-press")

    def test_navigation_hide_never_restores_or_reopens_the_old_target(self) -> None:
        control = InputMethodControl(mode="zh")
        control.handle("show", {})

        result, event = control.handle(
            "hide",
            {"restore_target": False, "reason": "navigation-back"},
        )

        self.assertFalse(result["visible"])
        self.assertIsNotNone(event)
        assert event is not None
        self.assertFalse(event.restore_target)
        self.assertEqual(event.reason, "navigation-back")
        _result, repeated = control.handle("hide", {})
        self.assertFalse(repeated.restore_target)
        self.assertEqual(repeated.reason, "navigation-back")

        for payload in (
            {"restore_target": 0},
            {"restore_target": None},
            {"reason": ""},
            {"reason": None},
            {"reason": "x" * 65},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                control.handle("hide", payload)

    def test_local_hide_defaults_to_no_focus_restore(self) -> None:
        control = InputMethodControl()
        control.handle("show", {})

        event = control.local_hide()

        self.assertFalse(event.restore_target)
        self.assertEqual(event.reason, "local")

    def test_mode_changes_use_one_shared_persistence_hook(self) -> None:
        saved: list[str] = []
        control = InputMethodControl(mode="en", on_mode_change=saved.append)

        control.handle("set_mode", {"mode": "zh"})
        control.update_ui_state(mode="zh", shift=False, composition="")
        control.update_ui_state(mode="numeric", shift=False, composition="")
        control.local_mode("symbols")
        control.handle("set_mode", {"mode": "symbols"})

        self.assertEqual(saved, ["zh", "numeric", "symbols", "symbols"])


if __name__ == "__main__":
    unittest.main()
