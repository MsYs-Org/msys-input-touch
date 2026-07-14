from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator


class InputBackendError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PointerState:
    """One root-coordinate pointer sample from the active X11 display."""

    x: int
    y: int
    mask: int


KEYSYMS = {
    "BackSpace": 0xFF08,
    "Return": 0xFF0D,
    "space": 0x0020,
    "Shift_L": 0xFFE1,
    "Shift_R": 0xFFE2,
    "Control_L": 0xFFE3,
    "Control_R": 0xFFE4,
}

XDOTOOL_NAMES = {
    "!": "exclam",
    "@": "at",
    "#": "numbersign",
    "$": "dollar",
    "%": "percent",
    "^": "asciicircum",
    "&": "ampersand",
    "*": "asterisk",
    "(": "parenleft",
    ")": "parenright",
    "-": "minus",
    "_": "underscore",
    "+": "plus",
    "=": "equal",
    "[": "bracketleft",
    "]": "bracketright",
    "{": "braceleft",
    "}": "braceright",
    "<": "less",
    ">": "greater",
    "/": "slash",
    ":": "colon",
    ";": "semicolon",
    ",": "comma",
    ".": "period",
}


def keysym_for_key(key: str) -> int:
    value = str(key or "")
    if value in KEYSYMS:
        return KEYSYMS[value]
    if len(value) == 1 and 0x20 <= ord(value) <= 0x7E:
        return ord(value)
    raise InputBackendError(f"unsupported X11 key: {key!r}")


def xdotool_key_name(key: str) -> str:
    value = str(key or "")
    if value in {"BackSpace", "Return", "space"}:
        return value
    if value in XDOTOOL_NAMES:
        return XDOTOOL_NAMES[value]
    if len(value) == 1 and value.isascii() and value.isprintable():
        return value
    raise InputBackendError(f"unsupported xdotool key: {key!r}")


def _library(name: str, fallback: str) -> ctypes.CDLL:
    resolved = ctypes.util.find_library(name) or fallback
    try:
        return ctypes.CDLL(resolved)
    except OSError as exc:
        raise InputBackendError(f"cannot load {resolved}: {exc}") from exc


class XTestBackend:
    """Small Xlib/XTest adapter; it never changes focus using a raw XID."""

    name = "xtest"
    available = True

    def __init__(self, display_name: str | None = None) -> None:
        self.display_name = display_name or os.environ.get("DISPLAY") or ""
        self._x11 = _library("X11", "libX11.so.6")
        self._xtst = _library("Xtst", "libXtst.so.6")
        self._configure()
        with self._display() as display:
            event = ctypes.c_int()
            error = ctypes.c_int()
            major = ctypes.c_int()
            minor = ctypes.c_int()
            if not self._xtst.XTestQueryExtension(
                display,
                ctypes.byref(event),
                ctypes.byref(error),
                ctypes.byref(major),
                ctypes.byref(minor),
            ):
                raise InputBackendError("X server does not expose XTEST")
        self.detail = "libXtst"

    def _configure(self) -> None:
        display = ctypes.c_void_p
        window = ctypes.c_ulong
        self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._x11.XOpenDisplay.restype = display
        self._x11.XCloseDisplay.argtypes = [display]
        self._x11.XCloseDisplay.restype = ctypes.c_int
        self._x11.XFlush.argtypes = [display]
        self._x11.XFlush.restype = ctypes.c_int
        self._x11.XSync.argtypes = [display, ctypes.c_int]
        self._x11.XSync.restype = ctypes.c_int
        self._x11.XGetInputFocus.argtypes = [
            display,
            ctypes.POINTER(window),
            ctypes.POINTER(ctypes.c_int),
        ]
        self._x11.XGetInputFocus.restype = ctypes.c_int
        self._x11.XQueryTree.argtypes = [
            display,
            window,
            ctypes.POINTER(window),
            ctypes.POINTER(window),
            ctypes.POINTER(ctypes.POINTER(window)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self._x11.XQueryTree.restype = ctypes.c_int
        self._x11.XDefaultRootWindow.argtypes = [display]
        self._x11.XDefaultRootWindow.restype = window
        self._x11.XQueryPointer.argtypes = [
            display,
            window,
            ctypes.POINTER(window),
            ctypes.POINTER(window),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self._x11.XQueryPointer.restype = ctypes.c_int
        self._x11.XFree.argtypes = [ctypes.c_void_p]
        self._x11.XFree.restype = ctypes.c_int
        self._x11.XKeysymToKeycode.argtypes = [display, ctypes.c_ulong]
        self._x11.XKeysymToKeycode.restype = ctypes.c_uint
        self._x11.XGetKeyboardMapping.argtypes = [
            display,
            ctypes.c_ubyte,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self._x11.XGetKeyboardMapping.restype = ctypes.POINTER(ctypes.c_ulong)
        self._xtst.XTestQueryExtension.argtypes = [
            display,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        self._xtst.XTestQueryExtension.restype = ctypes.c_int
        self._xtst.XTestFakeKeyEvent.argtypes = [
            display,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self._xtst.XTestFakeKeyEvent.restype = ctypes.c_int

    @contextmanager
    def _display(self) -> Iterator[ctypes.c_void_p]:
        name = self.display_name.encode("utf-8") if self.display_name else None
        display = self._x11.XOpenDisplay(name)
        if not display:
            raise InputBackendError(
                f"cannot open X11 display {self.display_name or '<default>'}"
            )
        try:
            yield display
        finally:
            # Keep the Xtst CDLL referenced until after Xlib close hooks run.
            self._x11.XCloseDisplay(display)

    def focused_window(self) -> int:
        """Return the current top-level XID without mutating X11 focus."""

        with self._display() as display:
            focus = ctypes.c_ulong()
            revert = ctypes.c_int()
            self._x11.XGetInputFocus(display, ctypes.byref(focus), ctypes.byref(revert))
            current = int(focus.value)
            if current <= 1:
                return 0
            for _ in range(64):
                root = ctypes.c_ulong()
                parent = ctypes.c_ulong()
                children = ctypes.POINTER(ctypes.c_ulong)()
                count = ctypes.c_uint()
                ok = self._x11.XQueryTree(
                    display,
                    current,
                    ctypes.byref(root),
                    ctypes.byref(parent),
                    ctypes.byref(children),
                    ctypes.byref(count),
                )
                if children:
                    self._x11.XFree(ctypes.cast(children, ctypes.c_void_p))
                if not ok or parent.value in {0, current}:
                    return current
                if parent.value == root.value:
                    return current
                current = int(parent.value)
            return current

    def pointer_state(self) -> PointerState:
        """Read root pointer position and button mask without taking a grab."""

        with self._display() as display:
            root = self._x11.XDefaultRootWindow(display)
            root_return = ctypes.c_ulong()
            child_return = ctypes.c_ulong()
            root_x = ctypes.c_int()
            root_y = ctypes.c_int()
            window_x = ctypes.c_int()
            window_y = ctypes.c_int()
            mask = ctypes.c_uint()
            if not self._x11.XQueryPointer(
                display,
                root,
                ctypes.byref(root_return),
                ctypes.byref(child_return),
                ctypes.byref(root_x),
                ctypes.byref(root_y),
                ctypes.byref(window_x),
                ctypes.byref(window_y),
                ctypes.byref(mask),
            ):
                raise InputBackendError("cannot query X11 root pointer")
            return PointerState(int(root_x.value), int(root_y.value), int(mask.value))

    def _binding(
        self,
        display: ctypes.c_void_p,
        key: str,
    ) -> tuple[int, bool]:
        symbol = keysym_for_key(key)
        keycode = int(self._x11.XKeysymToKeycode(display, symbol))
        if keycode <= 0 or keycode > 255:
            raise InputBackendError(f"key is absent from the X11 map: {key!r}")
        levels = ctypes.c_int()
        mapping = self._x11.XGetKeyboardMapping(
            display,
            ctypes.c_ubyte(keycode),
            1,
            ctypes.byref(levels),
        )
        if not mapping:
            raise InputBackendError(f"cannot inspect X11 key map for {key!r}")
        try:
            for index in range(min(2, max(0, int(levels.value)))):
                if int(mapping[index]) == symbol:
                    return keycode, index == 1
        finally:
            self._x11.XFree(ctypes.cast(mapping, ctypes.c_void_p))
        raise InputBackendError(
            f"key requires an unsupported X11 layout group: {key!r}"
        )

    def send_key(self, key: str, modifiers: tuple[str, ...] = ()) -> None:
        with self._display() as display:
            main_keycode, needs_shift = self._binding(display, key)
            requested = list(dict.fromkeys(str(item) for item in modifiers))
            if needs_shift and not any(item.startswith("Shift_") for item in requested):
                requested.append("Shift_L")
            modifier_codes = [self._binding(display, item)[0] for item in requested]
            pressed: list[int] = []
            main_pressed = False
            try:
                for keycode in modifier_codes:
                    if not self._xtst.XTestFakeKeyEvent(display, keycode, 1, 0):
                        raise InputBackendError("XTest rejected a modifier press")
                    pressed.append(keycode)
                if not self._xtst.XTestFakeKeyEvent(display, main_keycode, 1, 0):
                    raise InputBackendError("XTest rejected key press")
                main_pressed = True
                if not self._xtst.XTestFakeKeyEvent(display, main_keycode, 0, 0):
                    raise InputBackendError("XTest rejected key release")
                main_pressed = False
            finally:
                if main_pressed:
                    self._xtst.XTestFakeKeyEvent(display, main_keycode, 0, 0)
                for keycode in reversed(pressed):
                    self._xtst.XTestFakeKeyEvent(display, keycode, 0, 0)
                self._x11.XSync(display, 0)


class XdotoolBackend:
    name = "xdotool"
    available = True

    def __init__(self, executable: str | None = None) -> None:
        resolved = executable or shutil.which("xdotool")
        if not resolved:
            raise InputBackendError("xdotool is not installed")
        path = Path(resolved).expanduser().resolve()
        if not path.is_file():
            raise InputBackendError(f"xdotool is not a file: {path}")
        self.executable = str(path)
        self.detail = self.executable

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self.executable, *arguments],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InputBackendError(f"xdotool failed: {exc}") from exc
        if result.returncode != 0:
            raise InputBackendError(
                f"xdotool failed rc={result.returncode}: {result.stderr.strip()}"
            )
        return result

    def focused_window(self) -> int:
        result = self._run("getwindowfocus")
        try:
            value = int(result.stdout.strip(), 10)
        except ValueError as exc:
            raise InputBackendError("xdotool returned an invalid focus window") from exc
        return value if value > 1 else 0

    def pointer_state(self) -> PointerState | None:
        # Polling a subprocess at touch-frame cadence would cost more memory
        # and CPU than the fallback is worth.  Focus/lifecycle dismissal still
        # works when only xdotool is available.
        return None

    def send_key(self, key: str, modifiers: tuple[str, ...] = ()) -> None:
        modifier_names = {
            "Control_L": "ctrl",
            "Control_R": "ctrl",
            "Shift_L": "shift",
            "Shift_R": "shift",
        }
        prefix = [modifier_names[item] for item in modifiers if item in modifier_names]
        combo = "+".join([*prefix, xdotool_key_name(key)])
        self._run("key", "--clearmodifiers", combo)


class UnavailableBackend:
    name = "unavailable"
    available = False

    def __init__(self, detail: str) -> None:
        self.detail = str(detail)

    def focused_window(self) -> int:
        return 0

    def pointer_state(self) -> PointerState | None:
        return None

    def send_key(self, key: str, modifiers: tuple[str, ...] = ()) -> None:
        raise InputBackendError(self.detail or "input backend unavailable")


def create_backend(
    *,
    xtest_factory: Callable[[], object] = XTestBackend,
    xdotool_factory: Callable[[], object] = XdotoolBackend,
) -> object:
    errors: list[str] = []
    for factory in (xtest_factory, xdotool_factory):
        try:
            return factory()
        except (InputBackendError, OSError) as exc:
            errors.append(str(exc))
    return UnavailableBackend("; ".join(errors) or "no X11 input backend")


__all__ = [
    "InputBackendError",
    "PointerState",
    "UnavailableBackend",
    "XTestBackend",
    "XdotoolBackend",
    "create_backend",
    "keysym_for_key",
    "xdotool_key_name",
]
