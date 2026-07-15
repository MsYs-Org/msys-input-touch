from __future__ import annotations

import unittest
from unittest import mock

from msys_sdk import MsysConnectionClosed, MsysShutdown
from msys_input_touch.focus import FocusTarget
from msys_input_touch.service import (
    DEFAULT_HIDDEN_EXIT_DELAY_MS,
    error_packet,
    has_usable_focus_target,
    hidden_exit_delay_ms,
    request_component_stop,
)


class ServicePacketTests(unittest.TestCase):
    def test_recently_hidden_process_has_bounded_configurable_warm_grace(self) -> None:
        self.assertEqual(hidden_exit_delay_ms({}), DEFAULT_HIDDEN_EXIT_DELAY_MS)
        self.assertEqual(hidden_exit_delay_ms({"MSYS_INPUT_WARM_MS": "500"}), 750)
        self.assertEqual(hidden_exit_delay_ms({"MSYS_INPUT_WARM_MS": "25000"}), 25000)
        self.assertEqual(hidden_exit_delay_ms({"MSYS_INPUT_WARM_MS": "999999"}), 60000)
        self.assertEqual(
            hidden_exit_delay_ms({"MSYS_INPUT_WARM_MS": "invalid"}),
            DEFAULT_HIDDEN_EXIT_DELAY_MS,
        )

    def test_errors_are_typed_and_correlated(self) -> None:
        packet = error_packet(7, ValueError("unsupported mode"))
        self.assertEqual(packet, {
            "type": "error",
            "id": 7,
            "code": "INPUT_METHOD_ERROR",
            "message": "unsupported mode",
        })

    def test_hidden_start_and_show_without_a_checked_target_are_not_presented(self) -> None:
        self.assertFalse(has_usable_focus_target(None))
        self.assertFalse(has_usable_focus_target(FocusTarget("", 0x2A)))
        self.assertFalse(
            has_usable_focus_target(FocusTarget("msys.x11-window.v1:old", 1))
        )
        self.assertTrue(
            has_usable_focus_target(
                FocusTarget("msys.x11-window.v1:session-4:0x2a", 0x2A)
            )
        )

    def test_on_demand_release_requests_a_planned_self_stop(self) -> None:
        client = mock.Mock(component_id="org.msys.input.touch:keyboard")
        client.call.side_effect = MsysShutdown("planned stop")
        request_component_stop(client)
        client.call.assert_called_once_with(
            "msys.core",
            "stop",
            {"component": "org.msys.input.touch:keyboard"},
            timeout=2.0,
        )

    def test_channel_close_during_planned_stop_is_success(self) -> None:
        client = mock.Mock(component_id="org.msys.input.touch:keyboard")
        client.call.side_effect = MsysConnectionClosed("planned close")
        request_component_stop(client)

    def test_rejected_self_stop_is_not_silently_treated_as_success(self) -> None:
        client = mock.Mock(component_id="org.msys.input.touch:keyboard")
        client.call.return_value = {"type": "error", "code": "ACCESS_DENIED"}
        with self.assertRaisesRegex(RuntimeError, "ACCESS_DENIED"):
            request_component_stop(client)


if __name__ == "__main__":
    unittest.main()
