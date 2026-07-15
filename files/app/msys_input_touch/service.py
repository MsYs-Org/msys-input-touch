from __future__ import annotations

import argparse
import os
import queue
import threading
from typing import Any

from msys_sdk import MsysClient, MsysConnectionClosed, MsysShutdown

from .control import ControlEvent, InputMethodControl
from .focus import FocusManager, FocusTarget
from .lifecycle import (
    HiddenExitGate,
    InputVisibilityGuard,
    transition_hides_target,
)
from .model import INPUT_MODES, KeyboardModel
from .pinyin import PinyinDictionaryError, load_dictionary
from msys_sdk.ui_fonts import configure_tk_fonts
from .ui import TouchKeyboardView
from .worker import InjectionWorker
from .x11_input import PointerState, create_backend


VISIBILITY_POLL_MS = 45
DEFAULT_HIDDEN_EXIT_DELAY_MS = 15000
MIN_HIDDEN_EXIT_DELAY_MS = 750
MAX_HIDDEN_EXIT_DELAY_MS = 60000


def hidden_exit_delay_ms(environ: dict[str, str] | None = None) -> int:
    """Keep a recently used keyboard warm briefly, without baseline RSS.

    Mapping is still removed immediately on hide.  Only the already-started
    process gets a bounded grace period so moving between adjacent text fields
    does not repeatedly pay the Python/Tk cold-start cost.
    """

    selected = os.environ if environ is None else environ
    try:
        value = int(selected.get("MSYS_INPUT_WARM_MS", DEFAULT_HIDDEN_EXIT_DELAY_MS))
    except (TypeError, ValueError):
        return DEFAULT_HIDDEN_EXIT_DELAY_MS
    return max(MIN_HIDDEN_EXIT_DELAY_MS, min(MAX_HIDDEN_EXIT_DELAY_MS, value))


def error_packet(request_id: int, error: Exception) -> dict[str, Any]:
    return {
        "type": "error",
        "id": int(request_id),
        "code": "INPUT_METHOD_ERROR",
        "message": str(error),
    }


def has_usable_focus_target(target: FocusTarget | None) -> bool:
    """Only map a keyboard when its injection target is still meaningful."""

    return bool(
        target is not None
        and target.window_id.startswith("msys.x11-window.v1:")
        and target.native_xid > 1
    )


def request_component_stop(client: MsysClient) -> None:
    """Release this on-demand generation through Core's planned stop path.

    A component must not simply close its inherited control descriptor: Core
    correctly treats an unexplained EOF from a ready provider as a channel
    failure.  A self-stop request makes the shutdown explicit.  Current Core
    closes the channel while serving this call, so that closure is success.
    """

    try:
        response = client.call(
            "msys.core",
            "stop",
            {"component": client.component_id},
            timeout=2.0,
        )
    except (MsysConnectionClosed, MsysShutdown):
        return
    if response.get("type") != "return":
        raise RuntimeError(
            f"component self-stop rejected: {response.get('code', 'UNKNOWN')}"
        )


def run(
    *,
    standalone: bool = False,
    visible: bool = False,
    mode: str = "en",
) -> int:
    import tkinter as tk

    identity = os.environ.get("MSYS_WINDOW_IDENTITY", "org.msys.input.touch")
    root = tk.Tk(className=identity)
    configure_tk_fonts(root, default_size=9)
    root.title("msys-touch-input-host")
    root.withdraw()
    root.update_idletasks()

    try:
        dictionary = load_dictionary()
    except PinyinDictionaryError as exc:
        print(f"input-method: invalid Pinyin dictionary: {exc}", flush=True)
        root.destroy()
        return 2
    backend = create_backend()
    focus = FocusManager(backend)
    worker = InjectionWorker(focus, backend)
    control = InputMethodControl(mode=mode)
    control.set_runtime_status(
        backend_name=str(getattr(backend, "name", "unavailable")),
        backend_available=bool(getattr(backend, "available", False)),
    )
    model = KeyboardModel(dictionary, mode=mode)
    ui_events: queue.SimpleQueue[tuple[int, ControlEvent] | tuple[int, None]] = (
        queue.SimpleQueue()
    )
    visibility_revision = 0
    revision_lock = threading.Lock()
    visibility_guard = InputVisibilityGuard()
    hidden_exit_gate = HiddenExitGate()
    supervised_stop_requested = threading.Event()
    pointer_watch_available = True

    def update_target_status() -> None:
        control.set_runtime_status(has_focus_target=focus.target is not None)

    def capture_focus() -> None:
        try:
            focus.capture()
        except Exception as exc:
            print(f"input-method: focus capture unavailable: {exc}", flush=True)
        update_target_status()

    capture_lock = threading.Lock()
    capture_running = False

    def request_capture() -> None:
        nonlocal capture_running
        with capture_lock:
            if capture_running:
                return
            capture_running = True

        def work() -> None:
            nonlocal capture_running
            try:
                capture_focus()
            finally:
                with capture_lock:
                    capture_running = False

        threading.Thread(
            target=work,
            name="msys-touch-input-capture",
            daemon=True,
        ).start()

    def schedule_control(event: ControlEvent | None) -> None:
        nonlocal visibility_revision
        if event is None:
            return
        if event.action in {"show", "hide"}:
            with revision_lock:
                visibility_revision += 1
                revision = visibility_revision
        else:
            with revision_lock:
                revision = visibility_revision
        if event.action != "show":
            ui_events.put((revision, event))
            return

        def capture_then_show() -> None:
            capture_focus()
            with revision_lock:
                current = visibility_revision
            if revision == current and control.snapshot()["visible"]:
                ui_events.put((revision, event))

        threading.Thread(
            target=capture_then_show,
            name="msys-touch-input-show",
            daemon=True,
        ).start()

    view = TouchKeyboardView(
        root,
        model,
        control,
        worker,
        on_capture_request=request_capture,
        on_control_event=schedule_control,
    )

    def pointer_state() -> PointerState | None:
        nonlocal pointer_watch_available
        if not pointer_watch_available:
            return None
        read_pointer = getattr(backend, "pointer_state", None)
        if not callable(read_pointer):
            pointer_watch_available = False
            return None
        try:
            sample = read_pointer()
        except Exception as exc:
            # A lost display must not make an otherwise usable keyboard crash
            # or repeatedly log at touch-frame cadence.  Focus/lifecycle rules
            # remain active and the next on-demand start gets a fresh backend.
            pointer_watch_available = False
            print(f"input-method: pointer watcher disabled: {exc}", flush=True)
            return None
        return sample if isinstance(sample, PointerState) else None

    def focused_window() -> int | None:
        try:
            return int(backend.focused_window())
        except Exception:
            # Do not interpret a failed X query as an actual focus loss.
            return None

    def dismiss_automatically(
        reason: str,
        *,
        target: FocusTarget | None = None,
    ) -> None:
        event = control.dismiss(reason=reason, restore_target=False)
        if event is None:
            return
        # Never restore an old field after an outside click, Home, or an app
        # transition.  The expected target protects a simultaneous fresh show.
        if target is not None:
            focus.clear_target(target)
        schedule_control(event)

    def poll_visibility() -> None:
        if visibility_guard.active:
            target = focus.target
            decision = visibility_guard.observe(
                target=target,
                focused_xid=focused_window(),
                keyboard_xids=focus.keyboard_windows(),
                pointer=pointer_state(),
                panel=view.panel_bounds(),
            )
            if decision is not None:
                dismiss_automatically(decision.reason, target=target)
        root.after(VISIBILITY_POLL_MS if visibility_guard.active else 250, poll_visibility)

    def arm_hidden_exit(reason: str) -> None:
        """Release a hidden supervised generation after its animation window."""

        if standalone:
            return
        release_token = hidden_exit_gate.arm()

        def release_if_still_hidden() -> None:
            # The UI loop rechecks both this token and the typed visible state
            # before destroying Tk.  A show request racing this callback wins.
            ui_events.put((release_token, None))

        root.after(hidden_exit_delay_ms(), release_if_still_hidden)

    def request_supervised_exit() -> None:
        """Ask Core to stop us once, keeping Tk responsive until shutdown."""

        if supervised_stop_requested.is_set():
            return
        supervised_stop_requested.set()

        def work() -> None:
            if client is None:
                ui_events.put((0, None))
                return
            try:
                request_component_stop(client)
            except Exception as exc:
                # Compatibility fallback for a mismatched old Core/manifest.
                # It is intentionally exceptional; supported releases take
                # the planned stop path and never report control failure.
                print(f"input-method: supervised stop unavailable: {exc}", flush=True)
                ui_events.put((0, None))

        threading.Thread(
            target=work,
            name="msys-touch-input-release",
            daemon=True,
        ).start()

    def apply_visibility_lifecycle(event: ControlEvent) -> None:
        if event.action == "show":
            hidden_exit_gate.cancel()
            visibility_guard.arm(pointer_state())
            return
        if event.action != "hide":
            return
        visibility_guard.disarm()
        if not event.restore_target:
            focus.clear_target()
        if standalone:
            return
        # A hidden input method has no work left.  Finish its short hide
        # animation, then exit normally so a later role call creates a fresh
        # on-demand generation instead of retaining Tk/Python memory.
        arm_hidden_exit(event.reason)

    def pump_ui() -> None:
        while True:
            try:
                revision, event = ui_events.get_nowait()
            except queue.Empty:
                break
            if event is None:
                if revision == 0:
                    root.destroy()
                    return
                if hidden_exit_gate.should_exit(
                    revision,
                    visible=bool(control.snapshot()["visible"]),
                ):
                    if standalone:
                        root.destroy()
                        return
                    request_supervised_exit()
                continue
            with revision_lock:
                current = visibility_revision
            if event.action in {"show", "hide"} and revision != current:
                continue
            if event.action == "show" and not has_usable_focus_target(focus.target):
                # `start-component` intentionally starts hidden, and a role
                # show without a generation-checked editable target must not
                # leave a 32 MiB Tk process resident behind an invisible UI.
                hidden_exit_gate.cancel()
                dismiss_automatically("no-focus-target")
                continue
            view.apply_control_event(event)
            apply_visibility_lifecycle(event)
        root.after(30, pump_ui)

    client: MsysClient | None = None
    if not standalone:
        client = MsysClient.from_env()
        print("input-method: hello", flush=True)
        client.hello()
        client.subscribe("msys.lifecycle.transition")
        client.ready()
        # An operator may explicitly start the component rather than call the
        # role's show method.  It starts hidden by contract, so make that
        # generation self-reclaim unless a valid show cancels this timer.
        arm_hidden_exit("initial-hidden")
        client.event(
            "msys.role.ready",
            {"role": "input-method", "component": client.component_id},
        )
        print(
            "input-method: ready "
            f"backend={getattr(backend, 'name', 'unavailable')}",
            flush=True,
        )

        def ipc_loop() -> None:
            assert client is not None
            while True:
                message = client.recv(timeout=None)
                if not message or message.get("type") in {"eof", "shutdown"}:
                    ui_events.put((0, None))
                    return
                if message.get("type") == "event":
                    if str(message.get("topic") or "") == "msys.lifecycle.transition":
                        target = focus.target
                        if transition_hides_target(target, message.get("payload")):
                            dismiss_automatically("target-lifecycle", target=target)
                    continue
                if message.get("type") != "call":
                    continue
                request_id = int(message.get("id", 0))
                method = str(message.get("method") or "")
                payload = message.get("payload", {})
                try:
                    result, event = control.handle(method, payload)
                    client.send({
                        "type": "return",
                        "id": request_id,
                        "payload": result,
                    })
                    # Return first: a show callback may call window-manager and
                    # must not create a re-entrant wait on this provider call.
                    schedule_control(event)
                except Exception as exc:
                    client.send(error_packet(request_id, exc))

        threading.Thread(
            target=ipc_loop,
            name="msys-touch-input-ipc",
            daemon=True,
        ).start()
    elif visible:
        result, event = control.handle("show", {"mode": mode})
        del result
        schedule_control(event)

    root.after(30, pump_ui)
    root.after(VISIBILITY_POLL_MS, poll_visibility)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MSYS floating touch input method")
    parser.add_argument("--standalone", action="store_true")
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--mode", choices=sorted(INPUT_MODES), default="en")
    args = parser.parse_args(argv)
    return run(
        standalone=bool(args.standalone),
        visible=bool(args.visible),
        mode=str(args.mode),
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "error_packet",
    "has_usable_focus_target",
    "main",
    "request_component_stop",
    "run",
]
