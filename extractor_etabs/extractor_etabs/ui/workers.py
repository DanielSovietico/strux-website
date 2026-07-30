"""Hilo de trabajo único para todo lo que puede tardar.

Dos razones para que sea **un solo hilo persistente** y no un hilo por tarea:

* COM es *apartment threaded*: el objeto de ETABS pertenece al hilo que lo creó,
  así que todas las llamadas a la OAPI tienen que salir del mismo hilo.
* leer un modelo grande o un CSV de cientos de miles de renglones no debe
  congelar la ventana, y hacerlo en cola evita dos extracciones simultáneas
  peleándose por la misma conexión.

Las tareas se encolan con :meth:`SessionWorker.submit` y avisan su avance; el
usuario puede cancelar y la cancelación se propaga a la capa ``core`` a través
del callback de progreso.
"""

from __future__ import annotations

import queue
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, Signal

from ..core.extractors import Cancelled
from ..core.session import Session

#: Una tarea recibe la sesión y un callback de progreso ``(msg, hecho, total)``.
TaskFunc = Callable[[Session, Callable[[str, int, int], bool]], Any]


@dataclass
class _Job:
    name: str
    func: TaskFunc


class SessionWorker(QThread):
    """Ejecuta tareas sobre una :class:`Session` fuera del hilo de la interfaz."""

    progress = Signal(str, int, int)      # mensaje, hechos, total
    finished_job = Signal(str, object)    # nombre de la tarea, resultado
    failed = Signal(str, str)             # nombre de la tarea, mensaje
    log = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, session: Session, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.session = session
        self.session.on_log = self.log.emit
        self._queue: "queue.Queue[Optional[_Job]]" = queue.Queue()
        self._cancel = False
        self._stopping = False

    # ── API desde el hilo de la interfaz ────────────────────────────────────
    def submit(self, name: str, func: TaskFunc) -> None:
        self._cancel = False
        self._queue.put(_Job(name, func))

    def cancel(self) -> None:
        """Pide cancelar la tarea en curso (se atiende en el próximo avance)."""
        self._cancel = True

    def shutdown(self, timeout_ms: int = 4000) -> None:
        self._stopping = True
        self._cancel = True
        self._queue.put(None)
        if not self.wait(timeout_ms):       # pragma: no cover - salida forzada
            self.terminate()
            self.wait(1000)

    # ── hilo ────────────────────────────────────────────────────────────────
    def run(self) -> None:                  # pragma: no cover - requiere hilo
        # COM tiene que inicializarse en este hilo antes de tocar la OAPI.
        connection = self.session.connection
        if connection is not None:
            connection.initialize_thread()
        else:
            try:
                from ..core.etabs_api import EtabsConnection
                EtabsConnection().initialize_thread()
            except Exception:
                pass

        while not self._stopping:
            job = self._queue.get()
            if job is None:
                break
            self.busy_changed.emit(True)
            try:
                result = job.func(self.session, self._progress)
                self.finished_job.emit(job.name, result)
            except Cancelled:
                self.log.emit("Operación cancelada.")
                self.failed.emit(job.name, "Operación cancelada por el usuario.")
            except Exception as exc:
                self.log.emit(f"Error en «{job.name}»: {exc}")
                self.log.emit(traceback.format_exc(limit=6))
                self.failed.emit(job.name, str(exc) or exc.__class__.__name__)
            finally:
                self.busy_changed.emit(False)

    def _progress(self, message: str, done: int, total: int) -> bool:
        self.progress.emit(message, done, total)
        return not self._cancel
