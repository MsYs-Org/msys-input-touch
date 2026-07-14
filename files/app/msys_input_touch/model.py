from __future__ import annotations

from dataclasses import dataclass

from .pinyin import PinyinComposer, PinyinDictionary


INPUT_MODES = frozenset({"en", "zh", "numeric", "symbols"})


@dataclass(frozen=True, slots=True)
class InputAction:
    kind: str
    value: str = ""
    modifiers: tuple[str, ...] = ()
    refresh: bool = False


@dataclass(frozen=True, slots=True)
class KeySpec:
    token: str
    label: str
    weight: int = 1
    accent: bool = False


class KeyboardModel:
    """Toolkit-neutral keyboard and bounded Pinyin composition state."""

    def __init__(self, dictionary: PinyinDictionary, mode: str = "en") -> None:
        self.composer = PinyinComposer(dictionary)
        self.mode = "en"
        self.shift = False
        self.set_mode(mode)

    @property
    def composition(self) -> str:
        return self.composer.buffer

    @property
    def candidates(self) -> tuple[str, ...]:
        return self.composer.candidates if self.mode == "zh" else ()

    def set_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        if normalized not in INPUT_MODES:
            raise ValueError(f"unsupported input mode: {mode}")
        if normalized != self.mode:
            self.composer.clear()
            self.shift = False
        self.mode = normalized

    def handle(self, token: str) -> tuple[InputAction, ...]:
        value = str(token or "")
        if value.startswith("mode:"):
            self.set_mode(value.split(":", 1)[1])
            return (InputAction("refresh", refresh=True),)
        if value == "shift":
            self.shift = not self.shift
            return (InputAction("refresh", refresh=True),)
        if value == "hide":
            self.composer.clear()
            self.shift = False
            return (InputAction("hide", refresh=True),)
        if value == "backspace":
            if self.mode == "zh" and self.composer.backspace():
                return (InputAction("refresh", refresh=True),)
            return (InputAction("key", "BackSpace"),)
        if value == "enter":
            if self.mode == "zh" and self.composition:
                return (InputAction("text", self.composer.commit(), refresh=True),)
            return (InputAction("key", "Return"),)
        if value == "space":
            if self.mode == "zh" and self.composition:
                return (InputAction("text", self.composer.commit(), refresh=True),)
            return (InputAction("key", "space"),)
        if value.startswith("candidate:"):
            if self.mode != "zh" or not self.composition:
                return ()
            try:
                index = int(value.split(":", 1)[1])
            except ValueError:
                return ()
            if index < 0 or index >= len(self.candidates):
                return ()
            return (InputAction("text", self.composer.commit(index), refresh=True),)
        if value.startswith("char:"):
            character = value.split(":", 1)[1]
            if len(character) != 1:
                return ()
            if (
                self.mode == "zh"
                and character.isascii()
                and character.isalpha()
                and not self.shift
            ):
                if self.composer.feed(character):
                    return (InputAction("refresh", refresh=True),)
                return ()
            actions: list[InputAction] = []
            if self.mode == "zh" and self.composition:
                actions.append(InputAction("text", self.composer.commit(), refresh=True))
            if self.shift and character.isascii() and character.isalpha():
                character = character.upper()
            if self.shift:
                self.shift = False
            kind = "key" if ord(character) < 128 else "text"
            actions.append(InputAction(kind, character, refresh=True))
            return tuple(actions)
        return ()

    def layout(self) -> tuple[tuple[KeySpec, ...], ...]:
        if self.mode in {"en", "zh"}:
            letters = "QWERTYUIOP" if self.shift else "qwertyuiop"
            second = "ASDFGHJKL" if self.shift else "asdfghjkl"
            third = "ZXCVBNM" if self.shift else "zxcvbnm"
            language = (
                KeySpec("mode:zh", "中", accent=self.mode == "zh")
                if self.mode == "en"
                else KeySpec("mode:en", "EN", accent=True)
            )
            comma = "，" if self.mode == "zh" else ","
            period = "。" if self.mode == "zh" else "."
            return (
                tuple(KeySpec(f"char:{item.lower()}", item) for item in letters),
                tuple(KeySpec(f"char:{item.lower()}", item) for item in second),
                (
                    KeySpec("shift", "⇧", weight=2, accent=self.shift),
                    *(KeySpec(f"char:{item.lower()}", item) for item in third),
                    KeySpec("backspace", "⌫", weight=2),
                ),
                (
                    KeySpec("mode:numeric", "123", weight=2),
                    language,
                    KeySpec(f"char:{comma}", comma),
                    KeySpec("space", "Space", weight=4),
                    KeySpec(f"char:{period}", period),
                    KeySpec("enter", "↵", weight=2, accent=True),
                ),
            )
        if self.mode == "numeric":
            return (
                tuple(KeySpec(f"char:{item}", item) for item in "12345"),
                tuple(KeySpec(f"char:{item}", item) for item in "67890"),
                tuple(KeySpec(f"char:{item}", item) for item in "-/:;()"),
                (
                    KeySpec("mode:en", "ABC", weight=2),
                    KeySpec("mode:symbols", "#+=", weight=2),
                    KeySpec("space", "Space", weight=4),
                    KeySpec("backspace", "⌫", weight=2),
                    KeySpec("enter", "↵", weight=2, accent=True),
                ),
            )
        return (
            tuple(KeySpec(f"char:{item}", item) for item in "!@#$%"),
            tuple(KeySpec(f"char:{item}", item) for item in "^&*+="),
            tuple(KeySpec(f"char:{item}", item) for item in "[]{}<>"),
            (
                KeySpec("mode:en", "ABC", weight=2),
                KeySpec("mode:numeric", "123", weight=2),
                KeySpec("space", "Space", weight=4),
                KeySpec("backspace", "⌫", weight=2),
                KeySpec("enter", "↵", weight=2, accent=True),
            ),
        )


__all__ = [
    "INPUT_MODES",
    "InputAction",
    "KeySpec",
    "KeyboardModel",
]

