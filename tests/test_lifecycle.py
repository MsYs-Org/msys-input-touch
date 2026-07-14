from __future__ import annotations

import unittest

from msys_input_touch.focus import FocusTarget
from msys_input_touch.lifecycle import (
    HiddenExitGate,
    PRIMARY_BUTTON_MASK,
    InputVisibilityGuard,
    PanelBounds,
    transition_hides_target,
)
from msys_input_touch.x11_input import PointerState


TARGET = FocusTarget(
    "msys.x11-window.v1:session-4:0x2a",
    0x2A,
    identity="org.example.editor",
    component="org.example.editor:main",
)
PANEL = PanelBounds(60, 280, 200, 140)


class InputVisibilityGuardTests(unittest.TestCase):
    def observe(
        self,
        guard: InputVisibilityGuard,
        *,
        focus: int | None = 0x2A,
        pointer: PointerState | None = None,
    ):
        return guard.observe(
            target=TARGET,
            focused_xid=focus,
            keyboard_xids={0x88},
            pointer=pointer,
            panel=PANEL,
        )

    def test_opening_touch_is_baselined_then_new_outside_press_hides(self) -> None:
        guard = InputVisibilityGuard()
        guard.arm(PointerState(5, 5, PRIMARY_BUTTON_MASK))
        self.assertIsNone(
            self.observe(guard, pointer=PointerState(5, 5, PRIMARY_BUTTON_MASK))
        )
        self.assertIsNone(self.observe(guard, pointer=PointerState(5, 5, 0)))
        decision = self.observe(
            guard,
            pointer=PointerState(5, 5, PRIMARY_BUTTON_MASK),
        )
        self.assertEqual(decision.reason, "outside-primary-press")
        self.assertFalse(decision.restore_target)

    def test_keyboard_press_and_keyboard_focus_do_not_dismiss(self) -> None:
        guard = InputVisibilityGuard()
        guard.arm(PointerState(100, 300, 0))
        self.assertIsNone(
            self.observe(
                guard,
                focus=0x88,
                pointer=PointerState(100, 300, PRIMARY_BUTTON_MASK),
            )
        )

    def test_transient_foreign_focus_is_tolerated_then_persistent_migration_hides(self) -> None:
        guard = InputVisibilityGuard()
        guard.arm()
        self.assertIsNone(self.observe(guard, focus=0x99))
        self.assertIsNone(self.observe(guard, focus=0x99))
        decision = self.observe(guard, focus=0x99)
        self.assertEqual(decision.reason, "focus-left-target")

    def test_return_to_target_or_keyboard_resets_foreign_focus_streak(self) -> None:
        guard = InputVisibilityGuard()
        guard.arm()
        self.assertIsNone(self.observe(guard, focus=0x99))
        self.assertIsNone(self.observe(guard, focus=0x2A))
        self.assertIsNone(self.observe(guard, focus=0x99))
        self.assertIsNone(self.observe(guard, focus=0x88))
        self.assertIsNone(self.observe(guard, focus=0x99))

    def test_transient_zero_focus_is_tolerated_but_persistent_loss_hides(self) -> None:
        guard = InputVisibilityGuard()
        guard.arm()
        self.assertIsNone(self.observe(guard, focus=0))
        self.assertIsNone(self.observe(guard, focus=0))
        decision = self.observe(guard, focus=0)
        self.assertEqual(decision.reason, "focus-target-unavailable")

    def test_unavailable_focus_query_is_not_treated_as_focus_loss(self) -> None:
        guard = InputVisibilityGuard()
        guard.arm()
        for _ in range(5):
            self.assertIsNone(self.observe(guard, focus=None))


class LifecycleTransitionTests(unittest.TestCase):
    def test_exact_component_terminal_transition_hides_target(self) -> None:
        self.assertTrue(
            transition_hides_target(
                TARGET,
                {"phase": "closing", "component": "org.example.editor:main"},
            )
        )
        self.assertFalse(
            transition_hides_target(
                TARGET,
                {"phase": "launched", "component": "org.example.editor:main"},
            )
        )
        self.assertFalse(
            transition_hides_target(
                TARGET,
                {"phase": "closed", "component": "org.example.other:main"},
            )
        )

    def test_identity_is_the_safe_fallback_for_external_x11_windows(self) -> None:
        external = FocusTarget(
            "msys.x11-window.v1:session-4:0x99",
            0x99,
            identity="org.example.external",
            title="same title is unsafe",
        )
        self.assertTrue(
            transition_hides_target(
                external,
                {"phase": "failed", "identity": "org.example.external"},
            )
        )
        self.assertFalse(
            transition_hides_target(
                external,
                {"phase": "closed", "title": "same title is unsafe"},
            )
        )


class HiddenExitGateTests(unittest.TestCase):
    def test_initial_hidden_generation_releases_after_its_delay(self) -> None:
        gate = HiddenExitGate()
        token = gate.arm()
        self.assertTrue(gate.should_exit(token, visible=False))
        self.assertFalse(gate.should_exit(token, visible=True))

    def test_show_cancels_old_hidden_timer_then_hide_arms_a_fresh_one(self) -> None:
        gate = HiddenExitGate()
        initial = gate.arm()
        gate.cancel()  # a valid target received show before the timer fired
        self.assertFalse(gate.should_exit(initial, visible=False))
        hidden = gate.arm()  # Home/focus loss hid the mapped keyboard
        self.assertTrue(gate.should_exit(hidden, visible=False))
        self.assertFalse(gate.should_exit(initial, visible=False))

    def test_late_show_wins_over_a_release_token_already_queued(self) -> None:
        gate = HiddenExitGate()
        token = gate.arm()
        gate.cancel()
        self.assertFalse(gate.should_exit(token, visible=True))


if __name__ == "__main__":
    unittest.main()
