from __future__ import annotations

import unittest

from msys_input_touch.worker import InjectionJob, execute_job


class FakeFocus:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def ensure_target(self):
        self.calls += 1
        if self.error:
            raise self.error
        return object()


class FakeBackend:
    def __init__(self) -> None:
        self.calls = []

    def send_key(self, key, modifiers=()):
        self.calls.append((key, modifiers))


class InjectionWorkerTests(unittest.TestCase):
    def test_job_restores_focus_before_injection(self) -> None:
        focus = FakeFocus()
        backend = FakeBackend()
        result = execute_job(
            InjectionJob(7, "v", ("Control_L",), paste=True),
            focus=focus,  # type: ignore[arg-type]
            backend=backend,
        )
        self.assertTrue(result.ok)
        self.assertTrue(result.paste)
        self.assertEqual(focus.calls, 1)
        self.assertEqual(backend.calls, [("v", ("Control_L",))])

    def test_focus_failure_prevents_any_key_injection(self) -> None:
        focus = FakeFocus(RuntimeError("stale target"))
        backend = FakeBackend()
        result = execute_job(
            InjectionJob(8, "a"),
            focus=focus,  # type: ignore[arg-type]
            backend=backend,
        )
        self.assertFalse(result.ok)
        self.assertIn("stale target", result.error)
        self.assertEqual(backend.calls, [])

    def test_empty_job_is_focus_restore_only(self) -> None:
        focus = FakeFocus()
        backend = FakeBackend()
        result = execute_job(
            InjectionJob(9, ""),
            focus=focus,  # type: ignore[arg-type]
            backend=backend,
        )
        self.assertTrue(result.ok)
        self.assertEqual(backend.calls, [])


if __name__ == "__main__":
    unittest.main()

