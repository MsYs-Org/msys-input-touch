from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .model import INPUT_MODES


STATE_SCHEMA = "msys.input-method-state.v1"


def mode_layout(mode: str) -> str:
    if mode == "numeric":
        return "numeric"
    if mode == "symbols":
        return "symbols"
    return "letters"


def mode_locale(mode: str) -> str:
    return "zh-CN" if mode == "zh" else "en-US"


@dataclass(frozen=True, slots=True)
class ControlEvent:
    action: str
    mode: str
    # A navigation/lifecycle dismissal must not focus an application which the
    # user has just left.  Ordinary explicit hide keeps the historic focus
    # restore behavior for a second Back/key interaction.
    restore_target: bool = True
    reason: str = "requested"


class InputMethodControl:
    """Thread-safe typed role state shared by IPC and the Tk presenter."""

    def __init__(self, *, mode: str = "en") -> None:
        if mode not in INPUT_MODES:
            raise ValueError(f"unsupported input mode: {mode}")
        self._lock = threading.Lock()
        self._visible = False
        self._mode = mode
        self._shift = False
        self._composition = ""
        self._backend_name = "unavailable"
        self._backend_available = False
        self._has_focus_target = False
        self._last_hide_restore_target = True
        self._last_hide_reason = "requested"

    def set_runtime_status(
        self,
        *,
        backend_name: str | None = None,
        backend_available: bool | None = None,
        has_focus_target: bool | None = None,
    ) -> None:
        with self._lock:
            if backend_name is not None:
                self._backend_name = str(backend_name)
            if backend_available is not None:
                self._backend_available = bool(backend_available)
            if has_focus_target is not None:
                self._has_focus_target = bool(has_focus_target)

    def update_ui_state(self, *, mode: str, shift: bool, composition: str) -> None:
        if mode not in INPUT_MODES:
            raise ValueError(f"unsupported input mode: {mode}")
        with self._lock:
            self._mode = mode
            self._shift = bool(shift)
            self._composition = str(composition)[:24]

    def local_hide(
        self,
        *,
        restore_target: bool = True,
        reason: str = "local",
    ) -> ControlEvent:
        with self._lock:
            self._visible = False
            self._composition = ""
            event = ControlEvent(
                "hide",
                self._mode,
                restore_target=bool(restore_target),
                reason=str(reason or "local")[:64],
            )
            self._last_hide_restore_target = event.restore_target
            self._last_hide_reason = event.reason
            return event

    def dismiss(
        self,
        *,
        reason: str,
        restore_target: bool = False,
    ) -> ControlEvent | None:
        """Hide once for a local watcher, coalescing concurrent triggers."""

        with self._lock:
            if not self._visible:
                return None
            self._visible = False
            self._composition = ""
            event = ControlEvent(
                "hide",
                self._mode,
                restore_target=bool(restore_target),
                reason=str(reason or "automatic")[:64],
            )
            self._last_hide_restore_target = event.restore_target
            self._last_hide_reason = event.reason
            return event

    def local_mode(self, mode: str) -> ControlEvent:
        normalized = str(mode or "").strip().lower()
        if normalized not in INPUT_MODES:
            raise ValueError(f"unsupported input mode: {mode}")
        with self._lock:
            self._mode = normalized
            self._shift = False
            self._composition = ""
            return ControlEvent("mode", normalized)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "schema": STATE_SCHEMA,
                "visible": self._visible,
                "mode": self._mode,
                "layout": mode_layout(self._mode),
                "locale": mode_locale(self._mode),
                "shift": self._shift,
                "composition": self._composition,
                "backend": {
                    "name": self._backend_name,
                    "available": self._backend_available,
                },
                "has_focus_target": self._has_focus_target,
            }

    def handle(
        self,
        method: str,
        payload: object,
    ) -> tuple[dict[str, Any], ControlEvent | None]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        operation = str(method or "").strip()
        if operation == "status":
            if payload:
                raise ValueError("status payload must be empty")
            return self.snapshot(), None
        if operation not in {"show", "hide", "toggle", "set_mode"}:
            raise ValueError(f"unknown method {operation}")
        allowed = {"mode"} if operation in {"show", "toggle", "set_mode"} else set()
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unknown payload fields: {', '.join(unknown)}")
        requested_mode = payload.get("mode")
        if operation == "set_mode" and requested_mode is None:
            raise ValueError("mode is required")
        normalized_mode: str | None = None
        if requested_mode is not None:
            normalized_mode = str(requested_mode).strip().lower()
            if normalized_mode not in INPUT_MODES:
                raise ValueError(f"unsupported input mode: {requested_mode}")
        with self._lock:
            if normalized_mode is not None:
                self._mode = normalized_mode
                self._shift = False
                self._composition = ""
            if operation == "show":
                self._visible = True
                self._last_hide_restore_target = True
                self._last_hide_reason = "requested"
                event = ControlEvent("show", self._mode, reason="requested")
            elif operation == "hide":
                was_visible = self._visible
                self._visible = False
                self._composition = ""
                if was_visible:
                    self._last_hide_restore_target = True
                    self._last_hide_reason = "requested"
                event = ControlEvent(
                    "hide",
                    self._mode,
                    restore_target=self._last_hide_restore_target,
                    reason=self._last_hide_reason,
                )
            elif operation == "toggle":
                self._visible = not self._visible
                if self._visible:
                    self._last_hide_restore_target = True
                    self._last_hide_reason = "requested"
                else:
                    self._composition = ""
                    self._last_hide_restore_target = True
                    self._last_hide_reason = "requested"
                event = ControlEvent(
                    "show" if self._visible else "hide",
                    self._mode,
                    restore_target=(
                        True if self._visible else self._last_hide_restore_target
                    ),
                    reason="requested",
                )
            else:
                event = ControlEvent("mode", self._mode, reason="requested")
            result = {
                "ok": True,
                "schema": STATE_SCHEMA,
                "visible": self._visible,
                "mode": self._mode,
                "layout": mode_layout(self._mode),
                "locale": mode_locale(self._mode),
                "shift": self._shift,
                "composition": self._composition,
                "backend": {
                    "name": self._backend_name,
                    "available": self._backend_available,
                },
                "has_focus_target": self._has_focus_target,
            }
        return result, event


__all__ = [
    "ControlEvent",
    "InputMethodControl",
    "STATE_SCHEMA",
    "mode_layout",
    "mode_locale",
]
