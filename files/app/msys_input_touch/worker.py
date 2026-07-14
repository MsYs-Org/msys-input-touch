from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from .focus import FocusManager


@dataclass(frozen=True, slots=True)
class InjectionJob:
    identifier: int
    key: str
    modifiers: tuple[str, ...] = ()
    paste: bool = False


@dataclass(frozen=True, slots=True)
class InjectionResult:
    identifier: int
    ok: bool
    error: str = ""
    paste: bool = False


def execute_job(
    job: InjectionJob,
    *,
    focus: FocusManager,
    backend: object,
) -> InjectionResult:
    try:
        focus.ensure_target()
        if job.key:
            backend.send_key(job.key, job.modifiers)
        return InjectionResult(job.identifier, True, paste=job.paste)
    except Exception as exc:
        return InjectionResult(
            job.identifier,
            False,
            error=str(exc),
            paste=job.paste,
        )


class InjectionWorker:
    """Serialize focus restore and injection away from Tk's event thread."""

    def __init__(self, focus: FocusManager, backend: object) -> None:
        self.focus = focus
        self.backend = backend
        self.jobs: queue.Queue[InjectionJob | None] = queue.Queue(maxsize=64)
        self.results: queue.SimpleQueue[InjectionResult] = queue.SimpleQueue()
        self._thread = threading.Thread(
            target=self._run,
            name="msys-touch-input-worker",
            daemon=True,
        )
        self._thread.start()

    def submit(self, job: InjectionJob) -> bool:
        try:
            self.jobs.put_nowait(job)
            return True
        except queue.Full:
            self.results.put(
                InjectionResult(job.identifier, False, "input queue is full", job.paste)
            )
            return False

    def _run(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                return
            self.results.put(
                execute_job(job, focus=self.focus, backend=self.backend)
            )


__all__ = [
    "InjectionJob",
    "InjectionResult",
    "InjectionWorker",
    "execute_job",
]
