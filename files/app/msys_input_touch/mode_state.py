"""Small persistent default-mode policy shared by every input frontend."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import Mapping

from .model import INPUT_MODES


MODE_STATE_FILE = "input-mode.conf"


def locale_default_mode(environ: Mapping[str, str] | None = None) -> str:
    """Choose Chinese only for an explicitly Chinese MSYS session locale."""

    selected = os.environ if environ is None else environ
    locale = str(selected.get("MSYS_LOCALE", "")).strip().lower()
    locale = locale.split(".", 1)[0].replace("_", "-")
    return "zh" if locale == "zh" or locale.startswith("zh-") else "en"


def default_mode_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return package-owned persistent state shared by LVGL and Tk fallback."""

    selected = os.environ if environ is None else environ
    root = selected.get("MSYS_APP_STATE_DIR") or selected.get(
        "MSYS_COMPONENT_STATE_DIR"
    )
    if root:
        return Path(root) / MODE_STATE_FILE
    return Path.home() / ".local/state/msys-input-touch" / MODE_STATE_FILE


class InputModeStore:
    """Load and atomically replace one bounded mode token without a daemon."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.environ = os.environ if environ is None else environ
        self.path = Path(path) if path is not None else default_mode_path(self.environ)
        self._lock = threading.Lock()
        self._saved_mode: str | None = None

    def load(self) -> str:
        fallback = locale_default_mode(self.environ)
        try:
            value = self.path.read_text(encoding="ascii").strip().lower()
        except (FileNotFoundError, OSError, UnicodeError):
            return fallback
        if value not in INPUT_MODES:
            return fallback
        self._saved_mode = value
        return value

    def save(self, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        if normalized not in INPUT_MODES:
            raise ValueError(f"unsupported input mode: {mode}")
        with self._lock:
            if normalized == self._saved_mode and self.path.is_file():
                return
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self.path.with_name(
                f".{self.path.name}.tmp-{os.getpid()}"
            )
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    0o600,
                )
                with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                    stream.write(normalized + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                self._saved_mode = normalized
            finally:
                temporary.unlink(missing_ok=True)


__all__ = [
    "InputModeStore",
    "MODE_STATE_FILE",
    "default_mode_path",
    "locale_default_mode",
]
