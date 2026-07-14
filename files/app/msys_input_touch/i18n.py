from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

try:  # Release archives vendor msys_sdk beside this package.
    from msys_sdk import CatalogError, Translator
except (ImportError, ModuleNotFoundError):  # pragma: no cover - recovery UI
    CatalogError = ValueError  # type: ignore[assignment,misc]
    Translator = None  # type: ignore[assignment,misc]


CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "share" / "i18n" / "catalog.json"
)

FALLBACK = {
    "app.name": "Touch keyboard",
    "app.summary": "Floating English, symbol and bounded Pinyin input",
    "keyboard.title": "Touch keyboard",
    "keyboard.hide": "Hide",
    "keyboard.mode.en": "English",
    "keyboard.mode.zh": "Chinese",
    "keyboard.mode.numeric": "Numbers",
    "keyboard.mode.symbols": "Symbols",
    "keyboard.shift": "Shift",
    "keyboard.backspace": "Backspace",
    "keyboard.enter": "Enter",
    "keyboard.space": "Space",
    "keyboard.composition.empty": "Type Pinyin",
    "keyboard.status.ready": "Ready",
    "keyboard.status.no_target": "Tap a text field first",
    "keyboard.status.backend_unavailable": "Input injection unavailable",
    "keyboard.status.inject_failed": "Input failed: {error}",
}

class InputI18n:
    """Shared-catalog facade with the same recovery behavior as MSYS apps."""

    def __init__(
        self,
        catalog_path: str | os.PathLike[str] | None = None,
        *,
        locale: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path) if catalog_path else CATALOG_PATH
        self.load_error = ""
        self._translator: Any = None
        if Translator is not None:
            try:
                self._translator = Translator.from_file(
                    self.catalog_path,
                    locale,
                    environ=environ,
                )
            except (CatalogError, OSError, UnicodeError, ValueError) as exc:
                self.load_error = str(exc)

    @property
    def catalog(self) -> Any:
        if self._translator is None:
            raise RuntimeError("input-method translation catalog is unavailable")
        return self._translator.catalog

    @property
    def locale(self) -> str:
        if self._translator is None:
            return "en-US"
        return str(self._translator.resolved_locale)

    @property
    def fallback_chain(self) -> tuple[str, ...]:
        if self._translator is None:
            return ("en-US",)
        return tuple(str(item) for item in self._translator.fallback_chain)

    def set_locale(
        self,
        locale: str | None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> str:
        if self._translator is None:
            return "en-US"
        return str(self._translator.set_locale(locale, environ=environ))

    def text(
        self,
        key: str,
        params: Mapping[str, object] | None = None,
        *,
        fallback: str | None = None,
    ) -> str:
        english = fallback if fallback is not None else FALLBACK.get(key, key)
        if self._translator is not None:
            return str(self._translator.text(key, params, fallback=english))
        return _render_fallback(english, params)

    __call__ = text


def _render_fallback(
    template: str,
    params: Mapping[str, object] | None,
) -> str:
    rendered = template
    for key, value in (params or {}).items():
        if isinstance(value, str) or (
            isinstance(value, int) and not isinstance(value, bool)
        ):
            rendered = rendered.replace("{" + str(key) + "}", str(value))
    return rendered


I18N = InputI18n()


def text(key: str, params: Mapping[str, object] | None = None) -> str:
    return I18N.text(key, params)


__all__ = ["CATALOG_PATH", "FALLBACK", "I18N", "InputI18n", "text"]
