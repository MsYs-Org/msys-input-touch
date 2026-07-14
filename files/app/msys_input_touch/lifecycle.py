from __future__ import annotations

"""Small, toolkit-neutral visibility rules for the floating keyboard.

X11 does not expose a trustworthy cross-toolkit "text widget lost focus"
signal.  The role therefore only uses facts it can verify without grabbing
input: the generation-checked application surface, X11 focus, a primary
pointer transition outside the keyboard, and Core lifecycle events.
"""

from dataclasses import dataclass
from typing import Collection, Mapping

from .focus import FocusTarget, parse_native_xid
from .x11_input import PointerState


PRIMARY_BUTTON_MASK = 1 << 8
TERMINAL_TARGET_PHASES = frozenset({"closing", "closed", "failed"})
FOCUS_MIGRATION_POLLS = 3


@dataclass(frozen=True, slots=True)
class PanelBounds:
    x: int
    y: int
    width: int
    height: int

    def contains(self, x: int, y: int) -> bool:
        return (
            self.width > 0
            and self.height > 0
            and self.x <= int(x) < self.x + self.width
            and self.y <= int(y) < self.y + self.height
        )


@dataclass(frozen=True, slots=True)
class VisibilityDecision:
    """A local dismissal which must never restore an obsolete target focus."""

    reason: str
    restore_target: bool = False


class HiddenExitGate:
    """Generation gate for releasing an on-demand keyboard while hidden.

    Tk timers cannot be cancelled reliably once their callback has entered the
    event queue.  Each show invalidates earlier hidden-release tokens; the UI
    loop checks the token and the current control state immediately before it
    destroys the root.  This makes a late show request win over an old timer.
    """

    def __init__(self) -> None:
        self._revision = 0
        self._armed = False

    def arm(self) -> int:
        self._revision += 1
        self._armed = True
        return self._revision

    def cancel(self) -> None:
        self._revision += 1
        self._armed = False

    def should_exit(self, token: int, *, visible: bool) -> bool:
        return bool(
            self._armed
            and int(token) == self._revision
            and not bool(visible)
        )


def transition_hides_target(
    target: FocusTarget | None,
    payload: object,
) -> bool:
    """Return whether one Core transition terminally invalidates *target*.

    Component identity is preferred because it is exact.  External X11
    applications do not have a Core component, so their exact injected window
    identity is the safe fallback.  Titles are deliberately never compared.
    """

    if target is None or not isinstance(payload, Mapping):
        return False
    phase = str(payload.get("phase") or "").strip().lower()
    if phase not in TERMINAL_TARGET_PHASES:
        return False
    component = str(payload.get("component") or "").strip()
    if target.component and component:
        return target.component == component
    identity = str(payload.get("identity") or "").strip()
    return bool(target.identity and identity and target.identity == identity)


class InputVisibilityGuard:
    """Detect unambiguous reasons to dismiss a visible keyboard.

    The guard is driven by the Tk event loop only while the panel is visible.
    It deliberately does not grab the pointer or modify X11 focus.  The first
    pointer observation after show is only used as a baseline, so the touch
    which opened the keyboard cannot immediately dismiss it.
    """

    def __init__(self) -> None:
        self._active = False
        self._pointer_known = False
        self._primary_down = False
        self._zero_focus_polls = 0
        self._foreign_focus_polls = 0

    @property
    def active(self) -> bool:
        return self._active

    def arm(self, initial_pointer: PointerState | None = None) -> None:
        self._active = True
        self._zero_focus_polls = 0
        self._foreign_focus_polls = 0
        if initial_pointer is None:
            self._pointer_known = False
            self._primary_down = False
            return
        self._pointer_known = True
        self._primary_down = bool(initial_pointer.mask & PRIMARY_BUTTON_MASK)

    def disarm(self) -> None:
        self._active = False
        self._pointer_known = False
        self._primary_down = False
        self._zero_focus_polls = 0
        self._foreign_focus_polls = 0

    def observe(
        self,
        *,
        target: FocusTarget | None,
        focused_xid: object | None,
        keyboard_xids: Collection[int],
        pointer: PointerState | None,
        panel: PanelBounds | None,
    ) -> VisibilityDecision | None:
        if not self._active:
            return None

        focused = parse_native_xid(focused_xid)
        keyboard = {parse_native_xid(value) for value in keyboard_xids}
        keyboard.discard(0)
        if target is not None and focused_xid is not None:
            if focused and focused not in keyboard and focused != target.native_xid:
                # Window mapping, notification chrome, and the keyboard's own
                # override-redirect transitions can expose one foreign XID.
                # An outside primary press still dismisses in this same poll;
                # focus-only migration must remain stable for a short window.
                self._foreign_focus_polls += 1
                if self._foreign_focus_polls >= FOCUS_MIGRATION_POLLS:
                    return VisibilityDecision("focus-left-target")
            elif focused:
                self._foreign_focus_polls = 0
            # Mapping or unmapping an override-redirect panel can yield one
            # transient PointerRoot focus result.  Three consecutive samples
            # make an actual lost/closed target deterministic without hiding
            # during that harmless X11 transition.
            if focused == 0:
                self._foreign_focus_polls = 0
                self._zero_focus_polls += 1
                if self._zero_focus_polls >= 3:
                    return VisibilityDecision("focus-target-unavailable")
            else:
                self._zero_focus_polls = 0

        if pointer is None:
            return None
        primary_down = bool(pointer.mask & PRIMARY_BUTTON_MASK)
        if not self._pointer_known:
            self._pointer_known = True
            self._primary_down = primary_down
            return None
        pressed = primary_down and not self._primary_down
        self._primary_down = primary_down
        if pressed and (panel is None or not panel.contains(pointer.x, pointer.y)):
            return VisibilityDecision("outside-primary-press")
        return None


__all__ = [
    "InputVisibilityGuard",
    "HiddenExitGate",
    "FOCUS_MIGRATION_POLLS",
    "PRIMARY_BUTTON_MASK",
    "PanelBounds",
    "TERMINAL_TARGET_PHASES",
    "VisibilityDecision",
    "transition_hides_target",
]
