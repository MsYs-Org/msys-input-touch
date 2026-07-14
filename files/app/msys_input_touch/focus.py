from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from msys_sdk import MsysClient


class FocusTargetError(RuntimeError):
    pass


PublicCall = Callable[..., dict[str, Any]]


def return_payload(response: object, operation: str) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise FocusTargetError(f"{operation} returned a non-object response")
    if response.get("type") != "return":
        code = str(response.get("code") or "REMOTE_ERROR")
        message = str(response.get("message") or "remote call failed")
        raise FocusTargetError(f"{operation} failed: {code}: {message}")
    payload = response.get("payload", {})
    if not isinstance(payload, dict):
        raise FocusTargetError(f"{operation} returned a non-object payload")
    return dict(payload)


def parse_native_xid(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value if value > 1 else 0
    text = str(value or "").strip().lower()
    if not text:
        return 0
    try:
        parsed = int(text, 16 if text.startswith("0x") else 10)
    except ValueError:
        return 0
    return parsed if parsed > 1 else 0


@dataclass(frozen=True, slots=True)
class FocusTarget:
    window_id: str
    native_xid: int
    identity: str = ""
    title: str = ""
    component: str = ""


def target_from_window_list(
    native_xid: int,
    response: object,
) -> FocusTarget | None:
    target_xid = parse_native_xid(native_xid)
    if not target_xid:
        return None
    payload = return_payload(response, "window-manager.list_windows")
    windows = payload.get("windows", [])
    if not isinstance(windows, list):
        raise FocusTargetError("window-manager.list_windows returned invalid windows")
    for raw in windows[:128]:
        if not isinstance(raw, dict):
            continue
        if parse_native_xid(raw.get("native_id")) != target_xid:
            continue
        stable_id = str(raw.get("id") or raw.get("window_id") or "").strip()
        if not stable_id.startswith("msys.x11-window.v1:") or len(stable_id) >= 192:
            continue
        role = str(raw.get("role") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        if role and role != "application":
            continue
        if kind and kind not in {"application", "unknown"}:
            continue
        return FocusTarget(
            stable_id,
            target_xid,
            identity=str(raw.get("identity") or ""),
            title=str(raw.get("title") or ""),
            component=str(raw.get("component") or ""),
        )
    return None


class FocusManager:
    """Own a generation-checked target and never focus a raw captured XID."""

    def __init__(
        self,
        backend: object,
        *,
        public_call: PublicCall = MsysClient.public_call,
    ) -> None:
        self.backend = backend
        self.public_call = public_call
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._target: FocusTarget | None = None
        self._keyboard_windows: set[int] = set()

    @property
    def target(self) -> FocusTarget | None:
        with self._lock:
            return self._target

    def remember_keyboard_window(self, xid: int) -> None:
        value = parse_native_xid(xid)
        if value:
            with self._lock:
                self._keyboard_windows.add(value)

    def keyboard_windows(self) -> frozenset[int]:
        with self._lock:
            return frozenset(self._keyboard_windows)

    def is_keyboard_window(self, xid: object) -> bool:
        value = parse_native_xid(xid)
        with self._lock:
            return bool(value and value in self._keyboard_windows)

    def clear_target(self, expected: FocusTarget | None = None) -> bool:
        """Forget a target after user navigation or a terminal lifecycle event.

        ``expected`` avoids a delayed watcher clearing a newer target selected
        by a concurrent show request.
        """

        with self._lock:
            if self._target is None:
                return False
            if expected is not None and self._target != expected:
                return False
            self._target = None
            return True

    def capture(self) -> FocusTarget | None:
        # A show request and the panel's passive capture hint may overlap.
        # Serialize them so an older lookup cannot overwrite a newer target.
        with self._capture_lock:
            with self._lock:
                previous = self._target
            try:
                native = parse_native_xid(self.backend.focused_window())
            except Exception:
                with self._lock:
                    if self._target == previous:
                        self._target = None
                raise
            with self._lock:
                if not native or native in self._keyboard_windows:
                    return self._target
            try:
                response = self.public_call(
                    "role:window-manager",
                    "list_windows",
                    {},
                    timeout=3,
                )
                candidate = target_from_window_list(native, response)
            except Exception:
                # A failed lookup is not permission to inject into whatever
                # field happened to be selected before this show request.
                with self._lock:
                    if self._target == previous:
                        self._target = None
                raise
            with self._lock:
                if self._target != previous:
                    return self._target
                self._target = candidate
                return candidate

    def ensure_target(self) -> FocusTarget:
        target = self.target
        if target is None:
            raise FocusTargetError("no generation-checked text target is selected")
        current = parse_native_xid(self.backend.focused_window())
        if current == target.native_xid:
            return target
        payload = return_payload(
            self.public_call(
                "role:window-manager",
                "focus_window",
                {"window_id": target.window_id},
                timeout=3,
            ),
            "window-manager.focus_window",
        )
        if payload.get("ok") is False:
            reason = payload.get("reason") or payload.get("error") or "focus rejected"
            raise FocusTargetError(f"window-manager.focus_window failed: {reason}")
        return target


__all__ = [
    "FocusManager",
    "FocusTarget",
    "FocusTargetError",
    "parse_native_xid",
    "return_payload",
    "target_from_window_list",
]
