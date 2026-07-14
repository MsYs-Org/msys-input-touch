from __future__ import annotations

import os
import queue
from collections import deque
from typing import Any, Callable

from .control import ControlEvent, InputMethodControl
from .geometry import clamp_panel_position, keyboard_geometry
from .i18n import text
from .lifecycle import PanelBounds
from .model import InputAction, KeyboardModel, KeySpec
from msys_sdk.ui_fonts import font_spec
from msys_sdk.ui_identity import configure_tk_window_identity
from msys_sdk.ui_layout import bind_tk_text_wrap, responsive_columns
from .worker import InjectionJob, InjectionWorker


class TouchKeyboardView:
    """Small Tk presenter; model, focus policy, and injection remain replaceable."""

    def __init__(
        self,
        root: Any,
        model: KeyboardModel,
        control: InputMethodControl,
        worker: InjectionWorker,
        *,
        on_capture_request: Callable[[], None],
        on_control_event: Callable[[ControlEvent], None],
    ) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.model = model
        self.control = control
        self.worker = worker
        self.on_capture_request = on_capture_request
        self.on_control_event = on_control_event
        self.identity = os.environ.get(
            "MSYS_WINDOW_IDENTITY", "org.msys.input.touch"
        )
        self.panel: Any | None = None
        self.header: Any | None = None
        self.title_label: Any | None = None
        self.mode_label: Any | None = None
        self.composition_frame: Any | None = None
        self.composition_label: Any | None = None
        self.candidate_frame: Any | None = None
        self.keys_frame: Any | None = None
        self.status_label: Any | None = None
        initial_status = (
            text("keyboard.status.ready")
            if bool(getattr(worker.backend, "available", False))
            else text("keyboard.status.backend_unavailable")
        )
        self.status_var = tk.StringVar(master=root, value=initial_status)
        self.pending: deque[InputAction] = deque(maxlen=64)
        self.active_job: int | None = None
        self._job_revision = 0
        self._motion_revision = 0
        self._drag: tuple[int, int, int, int] | None = None
        self._drag_pending: tuple[int, int] | None = None
        self._drag_after: str | None = None
        self.root.after(30, self._pump_results)

    def _build_panel(self) -> None:
        if self.panel is not None:
            return
        tk = self.tk
        panel = tk.Toplevel(self.root, name="keyboard", class_=self.identity)
        panel.withdraw()
        configure_tk_window_identity(
            panel,
            "org.msys.input.touch",
            default_role="input-method",
            default_instance="keyboard",
        )
        panel.title(text("keyboard.title"))
        panel.configure(bg="#11151b", takefocus=0)
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        try:
            panel.attributes("-type", "dock")
        except tk.TclError:
            pass
        panel.resizable(False, False)
        self.panel = panel

        header = tk.Frame(panel, bg="#1b222b", takefocus=0)
        header.pack(fill="x")
        self.header = header
        handle = tk.Label(
            header,
            text="≡",
            bg="#1b222b",
            fg="#82b1ff",
            font=font_spec(panel, 14, "bold"),
            takefocus=0,
        )
        handle.pack(side="left", padx=(8, 4))
        title = tk.Label(
            header,
            text=text("keyboard.title"),
            bg="#1b222b",
            fg="#f2f5f8",
            font=font_spec(panel, 10, "bold"),
            takefocus=0,
        )
        title.pack(side="left")
        self.title_label = title
        self.mode_label = tk.Label(
            header,
            bg="#27313d",
            fg="#a9caff",
            padx=7,
            pady=2,
            font=font_spec(panel, 8, "bold"),
            takefocus=0,
        )
        self.mode_label.pack(side="left", padx=7)
        hide = tk.Label(
            header,
            text=text("keyboard.hide"),
            bg="#303945",
            fg="#eef2f6",
            padx=9,
            pady=4,
            cursor="hand2",
            takefocus=0,
        )
        hide.pack(side="right", padx=5, pady=3)
        self._bind_tile(hide, "hide", normal="#303945", pressed="#485563")

        self.composition_frame = tk.Frame(panel, bg="#151b22", height=30)
        self.composition_frame.pack(fill="x", padx=4, pady=(3, 1))
        self.composition_frame.pack_propagate(False)
        self.composition_label = tk.Label(
            self.composition_frame,
            bg="#151b22",
            fg="#9cc9ff",
            anchor="w",
            padx=6,
            font=font_spec(panel, 9, "bold"),
            takefocus=0,
        )
        self.composition_label.pack(side="left", fill="both", expand=True)
        self.candidate_frame = tk.Frame(self.composition_frame, bg="#151b22")
        self.candidate_frame.pack(side="right", fill="y")

        self.keys_frame = tk.Frame(panel, bg="#11151b")
        self.keys_frame.pack(fill="both", expand=True, padx=3)
        self.status_label = tk.Label(
            panel,
            textvariable=self.status_var,
            bg="#11151b",
            fg="#8f9dab",
            anchor="w",
            padx=7,
            font=font_spec(panel, 8),
            takefocus=0,
        )
        self.status_label.pack(fill="x", pady=(1, 2))
        bind_tk_text_wrap(
            title,
            header,
            horizontal_padding=176,
            minimum=54,
            maximum=150,
        )
        bind_tk_text_wrap(
            self.status_label,
            panel,
            horizontal_padding=14,
            minimum=120,
            maximum=560,
        )

        for widget in (header, handle, title, self.mode_label):
            widget.bind("<ButtonPress-1>", self._drag_start, add="+")
            widget.bind("<B1-Motion>", self._drag_motion, add="+")
            widget.bind("<ButtonRelease-1>", self._drag_end, add="+")
        panel.bind("<FocusIn>", self._focus_in, add="+")
        panel.bind(
            "<Enter>",
            lambda event: (
                self.on_capture_request() if event.widget is panel else None
            ),
            add="+",
        )
        panel.update_idletasks()
        self.worker.focus.remember_keyboard_window(self.root.winfo_id())
        self.worker.focus.remember_keyboard_window(panel.winfo_id())
        self._render()

    def _bind_tile(
        self,
        widget: Any,
        token: str,
        *,
        normal: str,
        pressed: str,
    ) -> None:
        def press(_event: Any) -> str:
            widget.configure(bg=pressed)
            return "break"

        def release(_event: Any) -> str:
            widget.configure(bg=normal)
            self._handle_token(token)
            return "break"

        def leave(_event: Any) -> None:
            widget.configure(bg=normal)

        widget.bind("<ButtonPress-1>", press, add="+")
        widget.bind("<ButtonRelease-1>", release, add="+")
        widget.bind("<Leave>", leave, add="+")

    def _key_label(self, key: KeySpec) -> str:
        labels = {
            "space": text("keyboard.space"),
            "shift": "⇧",
            "backspace": "⌫",
            "enter": "↵",
        }
        return labels.get(key.token, key.label)

    def _render(self) -> None:
        if self.panel is None or self.keys_frame is None:
            return
        tk = self.tk
        if self.mode_label is not None:
            self.mode_label.configure(text=text(f"keyboard.mode.{self.model.mode}"))
        if self.composition_label is not None:
            composition = self.model.composition
            self.composition_label.configure(
                text=(composition or text("keyboard.composition.empty"))
                if self.model.mode == "zh"
                else text(f"keyboard.mode.{self.model.mode}"),
                fg="#9cc9ff" if composition else "#7f8d9b",
            )
        if self.candidate_frame is not None:
            for child in self.candidate_frame.winfo_children():
                child.destroy()
            candidate_columns = responsive_columns(
                max(1, int(self.panel.winfo_width()) - 110),
                minimum_item_width=48,
                gap=2,
                maximum=5,
            )
            for index, candidate in enumerate(self.model.candidates[:candidate_columns]):
                tile = tk.Label(
                    self.candidate_frame,
                    text=candidate,
                    bg="#25303b",
                    fg="#f2f5f8",
                    padx=5,
                    pady=3,
                    font=font_spec(self.panel, 9, "bold"),
                    cursor="hand2",
                    takefocus=0,
                )
                tile.pack(side="left", padx=1, pady=2)
                self._bind_tile(
                    tile,
                    f"candidate:{index}",
                    normal="#25303b",
                    pressed="#436080",
                )
        for child in self.keys_frame.winfo_children():
            child.destroy()
        for row_keys in self.model.layout():
            row = tk.Frame(self.keys_frame, bg="#11151b")
            row.pack(fill="both", expand=True)
            for column, key in enumerate(row_keys):
                row.grid_columnconfigure(column, weight=max(1, key.weight), uniform="keys")
                normal = "#31567e" if key.accent else "#26303b"
                pressed = "#527cad" if key.accent else "#465463"
                tile = tk.Label(
                    row,
                    text=self._key_label(key),
                    bg=normal,
                    fg="#f4f6f8",
                    font=font_spec(self.panel, 9, "bold"),
                    borderwidth=0,
                    cursor="hand2",
                    takefocus=0,
                )
                tile.grid(row=0, column=column, sticky="nsew", padx=1, pady=1)
                self._bind_tile(tile, key.token, normal=normal, pressed=pressed)
            row.grid_rowconfigure(0, weight=1)
        self.control.update_ui_state(
            mode=self.model.mode,
            shift=self.model.shift,
            composition=self.model.composition,
        )

    def _handle_token(self, token: str) -> None:
        actions = self.model.handle(token)
        for action in actions:
            if action.kind == "hide":
                # Route local hide through the same serialized service path as
                # an mIPC call.  That path disarms the visibility watcher and
                # lets the on-demand provider exit cleanly after its animation.
                self.on_control_event(self.control.local_hide())
            elif action.kind in {"key", "text"}:
                if len(self.pending) < self.pending.maxlen:
                    self.pending.append(action)
            if action.refresh:
                self._render()
        self._start_next_job()

    def _start_next_job(self) -> None:
        if self.active_job is not None or not self.pending:
            return
        if not bool(getattr(self.worker.backend, "available", False)):
            self.pending.clear()
            self.status_var.set(text("keyboard.status.backend_unavailable"))
            return
        action = self.pending.popleft()
        self._job_revision += 1
        identifier = self._job_revision
        self.active_job = identifier
        if action.kind == "text":
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(action.value)
                self.root.update_idletasks()
            except self.tk.TclError as exc:
                self.status_var.set(
                    text("keyboard.status.inject_failed", {"error": str(exc)[:96]})
                )
                self.active_job = None
                self.root.after(30, self._start_next_job)
                return
            job = InjectionJob(
                identifier,
                "v",
                modifiers=("Control_L",),
                paste=True,
            )
        else:
            job = InjectionJob(identifier, action.value, action.modifiers)
        self.worker.submit(job)

    def _pump_results(self) -> None:
        while True:
            try:
                result = self.worker.results.get_nowait()
            except queue.Empty:
                break
            if result.ok:
                self.status_var.set(text("keyboard.status.ready"))
            else:
                message = result.error[:96]
                key = (
                    "keyboard.status.no_target"
                    if "target" in message.lower()
                    else "keyboard.status.inject_failed"
                )
                self.status_var.set(
                    text(key, {"error": message})
                    if key.endswith("inject_failed")
                    else text(key)
                )
            if result.identifier == self.active_job:
                self.active_job = None
                # Allow the target toolkit to request our clipboard selection
                # before another queued candidate can replace it.
                self.root.after(90 if result.paste and result.ok else 1, self._start_next_job)
        self.root.after(30, self._pump_results)

    def apply_control_event(self, event: ControlEvent) -> None:
        self.model.set_mode(event.mode)
        self._render()
        if event.action == "show":
            self.show()
        elif event.action == "hide":
            self.hide(restore_target=event.restore_target)

    def show(self) -> None:
        self._build_panel()
        assert self.panel is not None
        state = self.control.snapshot()
        if not state["backend"]["available"]:
            self.status_var.set(text("keyboard.status.backend_unavailable"))
        elif not state["has_focus_target"]:
            self.status_var.set(text("keyboard.status.no_target"))
        else:
            self.status_var.set(text("keyboard.status.ready"))
        inset_text = os.environ.get("MSYS_KEYBOARD_BOTTOM_INSET", "42")
        try:
            inset = int(inset_text)
        except ValueError:
            inset = 42
        geometry = keyboard_geometry(
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
            bottom_inset=inset,
        )
        self.panel.geometry(geometry.tk())
        self.panel.update_idletasks()
        self.panel.deiconify()
        self.panel.lift()
        self.panel.attributes("-topmost", True)
        self._animate(True, geometry.y)

    def hide(self, *, restore_target: bool = True) -> None:
        if self.panel is None:
            return
        self._cancel_drag_motion()
        self._drag = None
        if restore_target:
            self._submit_focus_restore()
        try:
            final_y = int(self.panel.winfo_y())
        except self.tk.TclError:
            return
        self._animate(False, final_y, on_complete=self.panel.withdraw)

    def panel_bounds(self) -> PanelBounds | None:
        """Return the live screen rectangle used by the passive tap watcher."""

        if self.panel is None or not bool(self.control.snapshot()["visible"]):
            return None
        try:
            if not bool(self.panel.winfo_viewable()):
                return None
            return PanelBounds(
                int(self.panel.winfo_rootx()),
                int(self.panel.winfo_rooty()),
                max(0, int(self.panel.winfo_width())),
                max(0, int(self.panel.winfo_height())),
            )
        except self.tk.TclError:
            return None

    def _animate(
        self,
        showing: bool,
        final_y: int,
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        if self.panel is None:
            return
        self._motion_revision += 1
        revision = self._motion_revision
        try:
            x = int(self.panel.winfo_x())
        except self.tk.TclError:
            return
        # A short slide gives feedback without alpha-compositing the complete
        # keyboard on every frame, which is expensive on the SPI output.
        frames = 4

        def step(index: int) -> None:
            if revision != self._motion_revision or self.panel is None:
                return
            amount = index / frames
            eased = 1.0 - (1.0 - amount) ** 3
            offset = round(12 * (1.0 - eased if showing else eased))
            try:
                self.panel.geometry(f"+{x}+{final_y + offset}")
            except self.tk.TclError:
                return
            if index < frames:
                self.root.after(18, lambda: step(index + 1))
            else:
                if showing:
                    try:
                        self.panel.geometry(f"+{x}+{final_y}")
                    except self.tk.TclError:
                        pass
                if on_complete is not None:
                    on_complete()

        step(0)

    def _focus_in(self, _event: Any) -> None:
        # A dock/override-redirect surface normally avoids focus. If a window
        # manager still assigns it, immediately restore the stable target.
        self._submit_focus_restore()

    def _submit_focus_restore(self) -> None:
        self._job_revision += 1
        self.worker.submit(InjectionJob(self._job_revision, ""))

    def _drag_start(self, event: Any) -> str:
        if self.panel is None:
            return "break"
        self._motion_revision += 1
        self._cancel_drag_motion()
        self._drag = (
            int(event.x_root),
            int(event.y_root),
            int(self.panel.winfo_x()),
            int(self.panel.winfo_y()),
        )
        return "break"

    def _drag_motion(self, event: Any) -> str:
        if self.panel is None or self._drag is None:
            return "break"
        start_x, start_y, panel_x, panel_y = self._drag
        x, y = clamp_panel_position(
            panel_x + int(event.x_root) - start_x,
            panel_y + int(event.y_root) - start_y,
            self.panel.winfo_width(),
            self.panel.winfo_height(),
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        self._drag_pending = (x, y)
        if self._drag_after is None:
            self._drag_after = self.root.after(16, self._flush_drag_motion)
        return "break"

    def _drag_end(self, _event: Any) -> str:
        if self._drag_after is not None:
            try:
                self.root.after_cancel(self._drag_after)
            except self.tk.TclError:
                pass
            self._drag_after = None
        self._flush_drag_motion()
        self._drag = None
        return "break"

    def _flush_drag_motion(self) -> None:
        self._drag_after = None
        position = self._drag_pending
        self._drag_pending = None
        if position is None or self.panel is None:
            return
        try:
            self.panel.geometry(f"+{position[0]}+{position[1]}")
        except self.tk.TclError:
            return

    def _cancel_drag_motion(self) -> None:
        if self._drag_after is not None:
            try:
                self.root.after_cancel(self._drag_after)
            except self.tk.TclError:
                pass
        self._drag_after = None
        self._drag_pending = None


__all__ = ["TouchKeyboardView"]
