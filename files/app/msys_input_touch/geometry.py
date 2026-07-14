from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeyboardGeometry:
    width: int
    height: int
    x: int
    y: int

    def tk(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


def keyboard_geometry(
    screen_width: int,
    screen_height: int,
    *,
    bottom_inset: int = 42,
) -> KeyboardGeometry:
    """Fit above navigation on 320x480 while remaining useful elsewhere."""

    screen_width = max(1, int(screen_width))
    screen_height = max(1, int(screen_height))
    margin = min(4, max(0, min(screen_width, screen_height) // 12))
    inset = min(max(0, int(bottom_inset)), max(0, screen_height // 3))
    available_height = max(1, screen_height - inset - margin * 2)
    width = max(1, min(600, screen_width - margin * 2))
    minimum_useful = 180 if screen_height >= 240 else 148
    desired_height = max(minimum_useful, round(screen_height * 0.42))
    height = max(1, min(230, desired_height, available_height))
    x = max(0, (screen_width - width) // 2)
    y = max(0, screen_height - inset - height - margin)
    return KeyboardGeometry(width, height, x, y)


def clamp_panel_position(
    x: int,
    y: int,
    width: int,
    height: int,
    screen_width: int,
    screen_height: int,
) -> tuple[int, int]:
    return (
        max(0, min(int(x), max(0, int(screen_width) - max(1, int(width))))),
        max(0, min(int(y), max(0, int(screen_height) - max(1, int(height))))),
    )


__all__ = ["KeyboardGeometry", "clamp_panel_position", "keyboard_geometry"]
