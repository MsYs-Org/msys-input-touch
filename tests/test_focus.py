from __future__ import annotations

import unittest

from msys_input_touch.focus import (
    FocusManager,
    FocusTarget,
    FocusTargetError,
    parse_native_xid,
    target_from_window_list,
)


WINDOW_ID = "msys.x11-window.v1:session-4:0x2a"


def window_response() -> dict:
    return {
        "type": "return",
        "payload": {
            "windows": [
                {
                    "id": WINDOW_ID,
                    "native_id": "0x2a",
                    "identity": "org.example.editor",
                    "title": "Editor",
                    "component": "org.example.editor:main",
                    "role": "application",
                }
            ]
        },
    }


class FakeBackend:
    def __init__(self, focused: int = 0x2A) -> None:
        self.focused = focused
        self.sent = []

    def focused_window(self) -> int:
        return self.focused

    def send_key(self, key, modifiers=()) -> None:
        self.sent.append((key, modifiers))


class FocusPolicyTests(unittest.TestCase):
    def test_native_ids_are_strictly_normalized(self) -> None:
        self.assertEqual(parse_native_xid("0x2a"), 42)
        self.assertEqual(parse_native_xid("42"), 42)
        for value in (None, True, 0, 1, "bad", ""):
            self.assertEqual(parse_native_xid(value), 0)

    def test_window_list_resolves_only_generation_checked_exact_xid(self) -> None:
        target = target_from_window_list(0x2A, window_response())
        self.assertEqual(target.window_id, WINDOW_ID)
        self.assertEqual(target.native_xid, 42)
        self.assertEqual(target.component, "org.example.editor:main")
        self.assertIsNone(target_from_window_list(0x99, window_response()))

        bad = window_response()
        bad["payload"]["windows"][0]["id"] = "0x2a"
        self.assertIsNone(target_from_window_list(0x2A, bad))

    def test_system_chrome_and_other_overlays_never_replace_text_target(self) -> None:
        for role in (
            "system-chrome",
            "navigation-bar",
            "notification-center",
            "task-switcher",
            "chooser",
            "screen-shield",
            "input-method",
        ):
            with self.subTest(role=role):
                response = window_response()
                response["payload"]["windows"][0]["role"] = role
                response["payload"]["windows"][0]["kind"] = "overlay"
                self.assertIsNone(target_from_window_list(0x2A, response))

    def test_capture_ignores_keyboard_and_retains_previous_target(self) -> None:
        backend = FakeBackend()
        calls = []

        def caller(*args, **kwargs):
            calls.append((*args, kwargs))
            return window_response()

        manager = FocusManager(backend, public_call=caller)
        target = manager.capture()
        self.assertEqual(target.window_id, WINDOW_ID)
        manager.remember_keyboard_window(0x88)
        backend.focused = 0x88
        self.assertEqual(manager.capture(), target)
        self.assertEqual(len(calls), 1)

    def test_unresolved_new_window_cannot_reuse_previous_text_target(self) -> None:
        backend = FakeBackend()
        manager = FocusManager(
            backend,
            public_call=lambda *_args, **_kwargs: window_response(),
        )
        self.assertIsNotNone(manager.capture())
        backend.focused = 0x99
        self.assertIsNone(manager.capture())
        self.assertIsNone(manager.target)

    def test_failed_current_window_lookup_invalidates_previous_target(self) -> None:
        backend = FakeBackend()
        failing = False

        def caller(*_args, **_kwargs):
            if failing:
                raise FocusTargetError("window catalog unavailable")
            return window_response()

        manager = FocusManager(backend, public_call=caller)
        self.assertIsNotNone(manager.capture())
        backend.focused = 0x99
        failing = True
        with self.assertRaisesRegex(FocusTargetError, "catalog unavailable"):
            manager.capture()
        self.assertIsNone(manager.target)

    def test_clear_target_cannot_erase_a_newer_capture(self) -> None:
        backend = FakeBackend()
        manager = FocusManager(backend, public_call=lambda *_args, **_kwargs: window_response())
        original = manager.capture()
        self.assertIsNotNone(original)
        replacement = FocusTarget(
            "msys.x11-window.v1:session-5:0x2b",
            0x2B,
            identity="org.example.other",
        )
        with manager._lock:  # test an interleaved fresh show capture
            manager._target = replacement
        self.assertFalse(manager.clear_target(original))
        self.assertEqual(manager.target, replacement)
        self.assertTrue(manager.clear_target(replacement))
        self.assertIsNone(manager.target)

    def test_ensure_skips_rpc_when_target_still_has_focus(self) -> None:
        backend = FakeBackend()
        calls = []
        manager = FocusManager(
            backend,
            public_call=lambda *args, **kwargs: (
                calls.append((args, kwargs)) or window_response()
            ),
        )
        manager.capture()
        calls.clear()
        self.assertEqual(manager.ensure_target().window_id, WINDOW_ID)
        self.assertEqual(calls, [])

    def test_focus_restore_uses_stable_typed_id_and_rejects_failure(self) -> None:
        backend = FakeBackend()
        calls = []

        def caller(target, method, payload, timeout):
            calls.append((target, method, payload, timeout))
            if method == "list_windows":
                return window_response()
            return {
                "type": "return",
                "payload": {"ok": True, "schema": "msys.window-action.v1"},
            }

        manager = FocusManager(backend, public_call=caller)
        manager.capture()
        backend.focused = 0x99
        self.assertEqual(manager.ensure_target().window_id, WINDOW_ID)
        self.assertEqual(calls[-1], (
            "role:window-manager",
            "focus_window",
            {"window_id": WINDOW_ID},
            3,
        ))

        def rejected(target, method, payload, timeout):
            if method == "list_windows":
                return window_response()
            return {"type": "return", "payload": {"ok": False, "reason": "stale"}}

        rejected_manager = FocusManager(backend, public_call=rejected)
        backend.focused = 0x2A
        rejected_manager.capture()
        backend.focused = 0x99
        with self.assertRaisesRegex(FocusTargetError, "stale"):
            rejected_manager.ensure_target()

    def test_no_target_never_falls_back_to_raw_xsetinputfocus(self) -> None:
        manager = FocusManager(
            FakeBackend(0),
            public_call=lambda *_args, **_kwargs: window_response(),
        )
        with self.assertRaisesRegex(FocusTargetError, "no generation-checked"):
            manager.ensure_target()


if __name__ == "__main__":
    unittest.main()
