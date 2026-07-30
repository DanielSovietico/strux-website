"""Sesión de trabajo: hilo conductor entre las fuentes y lo ya extraído.

Una sesión guarda el modelo vigente, los resultados vigentes y de dónde vino
cada cosa. La usan igual la interfaz de escritorio y la línea de comandos, así
que toda la lógica de «qué se puede hacer ahora» está en un solo lugar.

Combinaciones válidas de fuentes:

===================================  ====================  =========================
Geometría                            Resultados            Deflexiones calculables
===================================  ====================  =========================
ETABS abierto (OAPI)                 OAPI                  sí
ETABS abierto (OAPI)                 tabla exportada       sí
archivo .e2k                         tabla exportada       sí
archivo .e2k                          —                    no (faltan M3)
 —                                   tabla exportada       no (faltan secciones)
===================================  ====================  =========================
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .e2k_parser import parse_e2k_file
from .etabs_api import EtabsConnection, EtabsError, unavailable_reason
from .extractors import (
    ExtractionOptions, ModelReader, Progress, ResultsReader, compute_deflections,
)
from .model import ResultSet, StructuralModel
from .table_import import parse_table_file
from .units import unit_system


@dataclass
class Session:
    """Estado de una sesión de extracción."""

    model: Optional[StructuralModel] = None
    result: Optional[ResultSet] = None
    connection: Optional[EtabsConnection] = None
    log: List[str] = field(default_factory=list)
    on_log: Optional[Callable[[str], None]] = None

    # ── registro ────────────────────────────────────────────────────────────
    def note(self, message: str) -> None:
        self.log.append(message)
        if self.on_log is not None:
            self.on_log(message)

    # ── estado ──────────────────────────────────────────────────────────────
    @property
    def source_label(self) -> str:
        """Etiqueta corta de procedencia, como el indicador del programa original."""
        parts: List[str] = []
        if self.model is not None:
            origin = {"oapi": "ETABS abierto", "e2k": "archivo .e2k"}.get(
                self.model.info.source, self.model.info.source)
            name = os.path.basename(self.model.info.file or "") or "sin nombre"
            parts.append(f"Geometría: {origin} · {name}")
        else:
            parts.append("Geometría: sin cargar")
        if self.result is not None:
            origin = {"oapi": "OAPI", "tabla": "tabla exportada"}.get(
                self.result.source, self.result.source)
            parts.append(f"Resultados: {origin} · {self.result.origin or '—'}")
        else:
            parts.append("Resultados: sin cargar")
        return "   |   ".join(parts)

    @property
    def can_extract(self) -> bool:
        return self.connection is not None and self.connection.connected

    def oapi_reason(self) -> Optional[str]:
        return unavailable_reason()

    # ── fuentes de archivo ──────────────────────────────────────────────────
    def load_e2k(self, path: str) -> StructuralModel:
        self.note(f"Leyendo {os.path.basename(path)}…")
        model = parse_e2k_file(path)
        self.model = model
        counts = ", ".join(f"{k}={v}" for k, v in model.counts().items())
        if model.error:
            self.note(f"El archivo se leyó con problemas: {model.error}")
        else:
            self.note(f"Geometría leída del .e2k ({counts}).")
        return model

    def load_table(self, path: str, merge: bool = False) -> ResultSet:
        self.note(f"Importando {os.path.basename(path)}…")
        imported = parse_table_file(path)
        if imported.error:
            self.note(f"No se pudo usar la tabla: {imported.error}")
            if not merge:
                self.result = imported
            return imported
        if merge and self.result is not None:
            self.result.merge(imported)
            self.result.origin = f"{self.result.origin} + {imported.origin}"
        else:
            self.result = imported
        counts = ", ".join(f"{k}={v}" for k, v in imported.counts().items() if v)
        self.note(f"Tabla importada ({counts}); unidades {imported.units.label}.")
        return self.result or imported

    # ── ETABS ───────────────────────────────────────────────────────────────
    def connect(self, launch_if_needed: bool = True) -> str:
        """Se conecta a ETABS (adjuntándose o lanzándolo) y describe qué encontró."""
        connection = self.connection or EtabsConnection()
        info = connection.connect() if launch_if_needed else connection.attach()
        self.connection = connection
        filename = connection.model_filename() or "(sin modelo abierto)"
        locked = connection.is_locked()
        estado = {True: "análisis corrido", False: "análisis sin correr",
                  None: "estado de análisis desconocido"}[locked]
        message = (f"Conectado a {info.name or 'ETABS'} {info.version or ''} · "
                   f"{os.path.basename(filename)} · {estado}.")
        self.note(message)
        return message

    def open_model(self, path: str) -> str:
        if self.connection is None or not self.connection.connected:
            self.connect()
        assert self.connection is not None
        self.note(f"Abriendo {os.path.basename(path)} en ETABS…")
        self.connection.open_model(path)
        self.note(f"{os.path.basename(path)} abierto en ETABS.")
        return path

    def read_model(self, units_key: str = "Ton_m_C",
                   progress: Optional[Progress] = None,
                   kinds: Optional[List[str]] = None) -> StructuralModel:
        if self.connection is None or not self.connection.connected:
            raise EtabsError("Primero conéctate a ETABS.")
        model = ModelReader(self.connection).read(units_key, progress, kinds)
        self.model = model
        counts = ", ".join(f"{k}={v}" for k, v in model.counts().items())
        self.note(f"Modelo leído de ETABS ({counts}).")
        for item in model.missing:
            self.note(f"Faltante: {item}")
        return model

    def extract(self, options: ExtractionOptions,
                progress: Optional[Progress] = None) -> ResultSet:
        if self.connection is None or not self.connection.connected:
            raise EtabsError("Primero conéctate a ETABS.")
        if self.model is None:
            self.note("No hay geometría cargada: se lee el modelo primero.")
            self.read_model(options.units_key, progress)
        assert self.model is not None
        result = ResultsReader(self.connection).extract(self.model, options,
                                                        progress)
        self.result = result
        if result.error:
            self.note(f"La extracción no dio resultados: {result.error}")
        else:
            counts = ", ".join(f"{k}={v}" for k, v in result.counts().items() if v)
            self.note(f"Extracción terminada ({counts}).")
        for item in result.warnings:
            self.note(f"Aviso: {item}")
        return result

    # ── deflexiones sobre resultados ya cargados ────────────────────────────
    def add_deflections(self, options: ExtractionOptions,
                        progress: Optional[Progress] = None) -> int:
        if self.result is None:
            raise EtabsError("No hay resultados cargados.")
        if self.model is None:
            raise EtabsError(
                "Para calcular deflexiones hace falta la geometría (las "
                "dimensiones de la sección y el claro de cada trabe): "
                "conéctate a ETABS o carga el .e2k del modelo.")
        self.result.deflections.clear()
        count = compute_deflections(self.result, self.model, options, progress)
        self.note(f"Deflexiones calculadas en {count} claro(s).")
        return count

    def close(self) -> None:
        if self.connection is not None:
            self.connection.disconnect()
            self.connection = None
            self.note("Conexión con ETABS cerrada.")


def default_options(model: Optional[StructuralModel] = None,
                    units_key: str = "Ton_m_C") -> ExtractionOptions:
    """Opciones razonables de arranque: todo lo que el modelo permita."""
    options = ExtractionOptions(units_key=units_key)
    if model is not None:
        options.cases = list(model.load_cases)
        options.combos = list(model.load_combos)
        unit_system(units_key)      # valida la clave temprano
    return options
