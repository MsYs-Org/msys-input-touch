"""LVGL presenter bridge; focus, Pinyin and injection stay toolkit-neutral."""

from __future__ import annotations

import argparse
from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any

from msys_sdk import MsysClient

from .control import ControlEvent, InputMethodControl
from .focus import FocusManager
from .geometry import KeyboardGeometry, keyboard_geometry
from .lifecycle import (
    HiddenExitGate,
    InputVisibilityGuard,
    PanelBounds,
    transition_hides_target,
)
from .model import INPUT_MODES, InputAction, KeyboardModel
from .pinyin import load_dictionary
from .service import (
    error_packet,
    has_usable_focus_target,
    hidden_exit_delay_ms,
    request_component_stop,
)
from .worker import InjectionJob, InjectionWorker
from .x11_input import PointerState, create_backend


POLL_MS = 45


def native_binary() -> Path:
    configured = os.environ.get("MSYS_INPUT_LVGL_BINARY")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "bin" / "msys-input-touch-lvgl"


def panel_geometry(screen_width: int, screen_height: int) -> KeyboardGeometry:
    try:
        inset = int(os.environ.get("MSYS_KEYBOARD_BOTTOM_INSET", "42"))
    except ValueError:
        inset = 42
    return keyboard_geometry(screen_width, screen_height, bottom_inset=inset)


class NativePresenter:
    """One bounded line protocol to the C/LVGL window."""

    def __init__(
        self,
        binary: Path,
        geometry: KeyboardGeometry,
        events: queue.SimpleQueue[tuple[str, object]],
        *,
        output: str = "spi",
    ) -> None:
        path = Path(binary).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"LVGL keyboard binary is missing: {path}")
        self.events = events
        self._lock = threading.Lock()
        self._closing = False
        self.process = subprocess.Popen(
            [
                str(path),
                "--output",
                "hdmi" if output == "hdmi" else "spi",
                "--x",
                str(geometry.x),
                "--y",
                str(geometry.y),
                "--width",
                str(geometry.width),
                "--height",
                str(geometry.height),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            bufsize=1,
            close_fds=True,
        )
        threading.Thread(
            target=self._read,
            name="msys-input-lvgl-events",
            daemon=True,
        ).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                try:
                    packet = json.loads(line)
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if isinstance(packet, dict) and packet.get("type") == "token":
                    token = packet.get("token")
                    if isinstance(token, str) and 0 < len(token) <= 32:
                        self.events.put(("token", token))
        finally:
            if not self._closing:
                self.events.put(("frontend-exit", self.process.poll()))

    def send(self, packet: dict[str, object]) -> None:
        encoded = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            if self.process.poll() is not None or self.process.stdin is None:
                raise RuntimeError("LVGL keyboard frontend has exited")
            self.process.stdin.write(encoded + "\n")
            self.process.stdin.flush()

    def state(self, model: KeyboardModel) -> None:
        self.send(
            {
                "type": "state",
                "mode": model.mode,
                "shift": model.shift,
                "composition": model.composition,
                "candidates": list(model.candidates[:8]),
            }
        )

    def close(self) -> None:
        self._closing = True
        try:
            self.send({"type": "stop"})
        except (BrokenPipeError, OSError, RuntimeError):
            pass
        try:
            self.process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.process.kill()


def run(
    *,
    standalone: bool = False,
    visible: bool = False,
    mode: str = "en",
    run_ms: int = 0,
) -> int:
    import tkinter as tk

    backend = create_backend()
    focus = FocusManager(backend)
    control = InputMethodControl(mode=mode)
    control.set_runtime_status(
        backend_name=str(getattr(backend, "name", "unavailable")),
        backend_available=bool(getattr(backend, "available", False)),
    )
    model = KeyboardModel(load_dictionary(), mode=mode)
    worker = InjectionWorker(focus, backend)
    events: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
    identity = os.environ.get("MSYS_WINDOW_IDENTITY", "org.msys.input.touch")
    root = tk.Tk(className=identity)
    root.title("msys-touch-input-lvgl-bridge")
    root.withdraw()
    root.update_idletasks()
    geometry = panel_geometry(root.winfo_screenwidth(), root.winfo_screenheight())
    panel = PanelBounds(geometry.x, geometry.y, geometry.width, geometry.height)
    output = os.environ.get("MSYS_DISPLAY_OUTPUT", "spi")
    presenter = NativePresenter(native_binary(), geometry, events, output=output)
    presenter.state(model)

    visibility_guard = InputVisibilityGuard()
    hidden_gate = HiddenExitGate()
    pending: deque[InputAction] = deque(maxlen=64)
    active_job: int | None = None
    job_revision = 0
    visibility_revision = 0
    revision_lock = threading.Lock()
    stopping = threading.Event()
    client: MsysClient | None = None

    def pointer_state() -> PointerState | None:
        reader = getattr(backend, "pointer_state", None)
        if not callable(reader):
            return None
        try:
            value = reader()
        except Exception:
            return None
        return value if isinstance(value, PointerState) else None

    def focused_window() -> int | None:
        try:
            return int(backend.focused_window())
        except Exception:
            return None

    def send_state() -> None:
        control.update_ui_state(
            mode=model.mode,
            shift=model.shift,
            composition=model.composition,
        )
        presenter.state(model)

    def request_exit() -> None:
        if standalone:
            root.destroy()
            return
        if stopping.is_set():
            return
        stopping.set()

        def work() -> None:
            if client is not None:
                try:
                    request_component_stop(client)
                    return
                except Exception as exc:
                    print(f"input-method-lvgl: planned stop unavailable: {exc}", flush=True)
            events.put(("quit", None))

        threading.Thread(target=work, name="msys-input-lvgl-stop", daemon=True).start()

    def arm_hidden_exit() -> None:
        if standalone:
            return
        token = hidden_gate.arm()

        def release() -> None:
            if hidden_gate.should_exit(
                token, visible=bool(control.snapshot()["visible"])
            ):
                request_exit()

        root.after(hidden_exit_delay_ms(), release)

    def apply_event(event: ControlEvent) -> None:
        nonlocal geometry, panel, presenter, visibility_revision
        model.set_mode(event.mode)
        send_state()
        if event.action == "show":
            updated = panel_geometry(
                root.winfo_screenwidth(), root.winfo_screenheight()
            )
            if updated != geometry:
                presenter.close()
                geometry = updated
                panel = PanelBounds(
                    geometry.x, geometry.y, geometry.width, geometry.height
                )
                presenter = NativePresenter(
                    native_binary(), geometry, events, output=output
                )
                presenter.state(model)
            hidden_gate.cancel()
            with revision_lock:
                visibility_revision += 1
                revision = visibility_revision

            def capture() -> None:
                try:
                    target = focus.capture()
                except Exception as exc:
                    print(f"input-method-lvgl: focus capture failed: {exc}", flush=True)
                    target = None
                control.set_runtime_status(has_focus_target=target is not None)
                events.put(("captured", (revision, target)))

            threading.Thread(
                target=capture,
                name="msys-input-lvgl-focus",
                daemon=True,
            ).start()
        elif event.action == "hide":
            with revision_lock:
                visibility_revision += 1
            model.composer.clear()
            model.shift = False
            send_state()
            presenter.send({"type": "hide"})
            visibility_guard.disarm()
            if not event.restore_target:
                focus.clear_target()
            arm_hidden_exit()

    def dismiss(reason: str) -> None:
        event = control.dismiss(reason=reason, restore_target=False)
        if event is not None:
            apply_event(event)

    def start_next_job() -> None:
        nonlocal active_job, job_revision
        if active_job is not None or not pending:
            return
        action = pending.popleft()
        job_revision += 1
        active_job = job_revision
        if action.kind == "text":
            try:
                root.clipboard_clear()
                root.clipboard_append(action.value)
                root.update_idletasks()
            except tk.TclError as exc:
                print(f"input-method-lvgl: clipboard failed: {exc}", flush=True)
                active_job = None
                root.after(1, start_next_job)
                return
            worker.submit(
                InjectionJob(active_job, "v", modifiers=("Control_L",), paste=True)
            )
        else:
            worker.submit(InjectionJob(active_job, action.value, action.modifiers))

    def handle_token(token: str) -> None:
        for action in model.handle(token):
            if action.kind == "hide":
                apply_event(control.local_hide(reason="local-key"))
            elif action.kind in {"key", "text"} and len(pending) < pending.maxlen:
                pending.append(action)
            if action.refresh:
                send_state()
        start_next_job()

    def pump_results() -> None:
        nonlocal active_job
        while True:
            try:
                result = worker.results.get_nowait()
            except queue.Empty:
                break
            if not result.ok:
                print(f"input-method-lvgl: injection failed: {result.error[:128]}", flush=True)
            if result.identifier == active_job:
                active_job = None
                root.after(90 if result.paste and result.ok else 1, start_next_job)
        root.after(30, pump_results)

    def pump_events() -> None:
        while True:
            try:
                kind, payload = events.get_nowait()
            except queue.Empty:
                break
            if kind == "token" and isinstance(payload, str):
                handle_token(payload)
            elif kind == "captured" and isinstance(payload, tuple):
                revision, target = payload
                with revision_lock:
                    current = visibility_revision
                if revision != current or not control.snapshot()["visible"]:
                    continue
                if not has_usable_focus_target(target):
                    dismiss("no-focus-target")
                    continue
                send_state()
                presenter.send({"type": "show"})
                visibility_guard.arm(pointer_state())
            elif kind == "frontend-exit":
                print(f"input-method-lvgl: frontend exited rc={payload}", flush=True)
                request_exit()
            elif kind == "control" and isinstance(payload, ControlEvent):
                apply_event(payload)
            elif kind == "dismiss" and isinstance(payload, str):
                dismiss(payload)
            elif kind == "quit":
                root.destroy()
                return
        root.after(20, pump_events)

    def poll_visibility() -> None:
        if visibility_guard.active:
            decision = visibility_guard.observe(
                target=focus.target,
                focused_xid=focused_window(),
                keyboard_xids=focus.keyboard_windows(),
                pointer=pointer_state(),
                panel=panel,
            )
            if decision is not None:
                dismiss(decision.reason)
        root.after(POLL_MS if visibility_guard.active else 250, poll_visibility)

    if standalone:
        if visible:
            control.handle("show", {"mode": mode})
            presenter.send({"type": "show"})
    else:
        client = MsysClient.from_env()
        client.hello()
        client.subscribe("msys.lifecycle.transition")
        client.ready()
        client.event(
            "msys.role.ready",
            {"role": "input-method", "component": client.component_id},
        )
        arm_hidden_exit()

        def ipc_loop() -> None:
            assert client is not None
            while True:
                message = client.recv(timeout=None)
                if not message or message.get("type") in {"eof", "shutdown"}:
                    events.put(("quit", None))
                    return
                if message.get("type") == "event":
                    if (
                        message.get("topic") == "msys.lifecycle.transition"
                        and transition_hides_target(focus.target, message.get("payload"))
                    ):
                        events.put(("dismiss", "target-lifecycle"))
                    continue
                if message.get("type") != "call":
                    continue
                request_id = int(message.get("id", 0))
                try:
                    result, event = control.handle(
                        str(message.get("method") or ""),
                        message.get("payload", {}),
                    )
                    client.send({"type": "return", "id": request_id, "payload": result})
                    if event is not None:
                        events.put(("control", event))
                except Exception as exc:
                    client.send(error_packet(request_id, exc))

        threading.Thread(
            target=ipc_loop,
            name="msys-input-lvgl-ipc",
            daemon=True,
        ).start()

    root.after(20, pump_events)
    root.after(30, pump_results)
    root.after(POLL_MS, poll_visibility)
    if run_ms > 0:
        root.after(max(1, min(60000, int(run_ms))), root.destroy)
    root.mainloop()
    presenter.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MSYS LVGL touch keyboard bridge")
    parser.add_argument("--standalone", action="store_true")
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--mode", choices=sorted(INPUT_MODES), default="en")
    parser.add_argument("--run-ms", type=int, default=0)
    args = parser.parse_args(argv)
    return run(
        standalone=bool(args.standalone),
        visible=bool(args.visible),
        mode=str(args.mode),
        run_ms=max(0, int(args.run_ms)),
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["NativePresenter", "main", "native_binary", "panel_geometry", "run"]
