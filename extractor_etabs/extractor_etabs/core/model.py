"""Modelo de datos normalizado.

Todas las fuentes (OAPI, .e2k, tablas exportadas) se traducen a estas mismas
estructuras, de modo que la interfaz y los exportadores tengan un único formato
que entender. Los resultados se representan como filas planas porque así se
mapean sin fricción a una tabla, a un CSV y a un diagrama.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .units import UnitSystem

# ── Geometría ───────────────────────────────────────────────────────────────


@dataclass
class Story:
    name: str
    elevation: Optional[float] = None
    height: Optional[float] = None
    is_base: bool = False


@dataclass
class GridLine:
    label: str
    direction: str          # 'X' o 'Y'
    ordinate: float


@dataclass
class Point:
    name: str
    x: float
    y: float
    z: Optional[float] = None


@dataclass
class Section:
    name: str
    material: Optional[str] = None
    shape: Optional[str] = None
    b_cm: Optional[float] = None       # ancho (dirección 2)
    h_cm: Optional[float] = None       # peralte total (dirección 3)
    dim_source: Optional[str] = None   # 'api' | 'e2k' | 'nombre'

    @property
    def area_cm2(self) -> Optional[float]:
        if self.b_cm is None or self.h_cm is None:
            return None
        return self.b_cm * self.h_cm

    @property
    def inertia_cm4(self) -> Optional[float]:
        """Inercia bruta de la sección rectangular respecto al eje fuerte."""
        if self.b_cm is None or self.h_cm is None:
            return None
        return self.b_cm * self.h_cm ** 3 / 12.0


@dataclass
class FrameElement:
    """Barra (trabe, columna o diagonal) con su geometría resuelta."""

    name: str                          # nombre único del objeto en ETABS
    label: Optional[str] = None        # etiqueta visible (B12, C3…)
    story: Optional[str] = None
    section: Optional[str] = None
    kind: str = "BEAM"                 # BEAM | COLUMN | BRACE | OTHER
    point_i: Optional[str] = None
    point_j: Optional[str] = None
    xi: Optional[float] = None
    yi: Optional[float] = None
    zi: Optional[float] = None
    xj: Optional[float] = None
    yj: Optional[float] = None
    zj: Optional[float] = None
    direction: Optional[str] = None    # 'X' | 'Y' | 'Z' | 'D' (diagonal)
    grid_line: Optional[str] = None    # eje sobre el que corre
    grid_i: Optional[str] = None
    grid_j: Optional[str] = None

    @property
    def length(self) -> Optional[float]:
        if None in (self.xi, self.yi, self.xj, self.yj):
            return None
        dz = (self.zj or 0.0) - (self.zi or 0.0)
        return math.sqrt((self.xj - self.xi) ** 2 + (self.yj - self.yi) ** 2 + dz ** 2)

    @property
    def display_name(self) -> str:
        if self.label and self.label != self.name:
            return f"{self.label} ({self.name})"
        return self.name


@dataclass
class ModelInfo:
    program: Optional[str] = None
    version: Optional[str] = None
    title: Optional[str] = None
    file: Optional[str] = None
    source: str = "desconocida"        # 'oapi' | 'e2k' | 'tabla'
    units: UnitSystem = field(default_factory=UnitSystem)


@dataclass
class StructuralModel:
    """Geometría del modelo, independiente de cómo se obtuvo."""

    info: ModelInfo = field(default_factory=ModelInfo)
    stories: List[Story] = field(default_factory=list)
    grids_x: List[GridLine] = field(default_factory=list)
    grids_y: List[GridLine] = field(default_factory=list)
    points: Dict[str, Point] = field(default_factory=dict)
    sections: Dict[str, Section] = field(default_factory=dict)
    frames: List[FrameElement] = field(default_factory=list)
    load_patterns: List[str] = field(default_factory=list)
    load_cases: List[str] = field(default_factory=list)
    load_combos: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    # ── consultas de conveniencia ──
    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.frames)

    @property
    def all_cases(self) -> List[str]:
        """Casos y combinaciones, sin repetir y en orden estable."""
        seen: Dict[str, None] = {}
        for name in list(self.load_cases) + list(self.load_combos):
            seen.setdefault(name, None)
        return list(seen)

    def beams(self) -> List[FrameElement]:
        return [f for f in self.frames if f.kind == "BEAM"]

    def story_names(self) -> List[str]:
        return [s.name for s in self.stories]

    def frames_by_story(self) -> Dict[str, List[FrameElement]]:
        out: Dict[str, List[FrameElement]] = {}
        for f in self.frames:
            out.setdefault(f.story or "(sin nivel)", []).append(f)
        return out

    def frame(self, name: str) -> Optional[FrameElement]:
        for f in self.frames:
            if f.name == name:
                return f
        return None

    def counts(self) -> Dict[str, int]:
        return {
            "niveles": len(self.stories),
            "ejes": len(self.grids_x) + len(self.grids_y),
            "nudos": len(self.points),
            "barras": len(self.frames),
            "trabes": len(self.beams()),
            "columnas": len([f for f in self.frames if f.kind == "COLUMN"]),
            "secciones": len(self.sections),
            "casos": len(self.load_cases),
            "combinaciones": len(self.load_combos),
        }


# ── Resultados ──────────────────────────────────────────────────────────────


@dataclass
class FrameForceRow:
    """Un renglón de elementos mecánicos en una estación de una barra."""

    story: str
    frame: str
    label: Optional[str]
    case: str
    step_type: Optional[str]
    step_num: Optional[float]
    station: float
    P: Optional[float] = None
    V2: Optional[float] = None
    V3: Optional[float] = None
    T: Optional[float] = None
    M2: Optional[float] = None
    M3: Optional[float] = None

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.story, self.frame, self.case)


@dataclass
class JointDisplRow:
    """Desplazamientos y rotaciones de un nudo."""

    story: Optional[str]
    point: str
    label: Optional[str]
    case: str
    step_type: Optional[str]
    step_num: Optional[float]
    U1: Optional[float] = None
    U2: Optional[float] = None
    U3: Optional[float] = None
    R1: Optional[float] = None
    R2: Optional[float] = None
    R3: Optional[float] = None


@dataclass
class DriftRow:
    """Deriva de entrepiso."""

    story: str
    case: str
    step_type: Optional[str]
    direction: Optional[str]
    drift: Optional[float]
    label: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None


@dataclass
class DeflectionRow:
    """Deflexión de una trabe calculada por doble integración de M3/EI."""

    story: str
    frame: str
    case: str
    station: float
    deflection: Optional[float]        # en la longitud del sistema de unidades
    span: Optional[float] = None
    is_max: bool = False


@dataclass
class ReactionRow:
    case: str
    step_type: Optional[str]
    FX: Optional[float] = None
    FY: Optional[float] = None
    FZ: Optional[float] = None
    MX: Optional[float] = None
    MY: Optional[float] = None
    MZ: Optional[float] = None


@dataclass
class ResultSet:
    """Todo lo extraído en una corrida, con su procedencia y sus faltantes."""

    source: str = "desconocida"        # 'oapi' | 'tabla'
    origin: Optional[str] = None       # archivo o tabla de la que provino
    units: UnitSystem = field(default_factory=UnitSystem)
    frame_forces: List[FrameForceRow] = field(default_factory=list)
    displacements: List[JointDisplRow] = field(default_factory=list)
    drifts: List[DriftRow] = field(default_factory=list)
    deflections: List[DeflectionRow] = field(default_factory=list)
    reactions: List[ReactionRow] = field(default_factory=list)
    cases: List[str] = field(default_factory=list)
    stories: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.row_count > 0

    @property
    def row_count(self) -> int:
        return (len(self.frame_forces) + len(self.displacements) + len(self.drifts)
                + len(self.deflections) + len(self.reactions))

    def counts(self) -> Dict[str, int]:
        return {
            "fuerzas": len(self.frame_forces),
            "desplazamientos": len(self.displacements),
            "derivas": len(self.drifts),
            "deflexiones": len(self.deflections),
            "reacciones": len(self.reactions),
        }

    def merge(self, other: "ResultSet") -> "ResultSet":
        """Agrega los renglones de ``other`` conservando la procedencia propia."""
        self.frame_forces.extend(other.frame_forces)
        self.displacements.extend(other.displacements)
        self.drifts.extend(other.drifts)
        self.deflections.extend(other.deflections)
        self.reactions.extend(other.reactions)
        for name in other.cases:
            if name not in self.cases:
                self.cases.append(name)
        for name in other.stories:
            if name not in self.stories:
                self.stories.append(name)
        for msg in other.missing:
            if msg not in self.missing:
                self.missing.append(msg)
        self.warnings.extend(other.warnings)
        if self.error is None:
            self.error = other.error
        return self

    # ── agrupaciones para diagramas ──
    def series(self, story: str, frame: str, case: str) -> List[FrameForceRow]:
        """Estaciones de una barra/caso, ordenadas por distancia."""
        rows = [r for r in self.frame_forces
                if r.frame == frame and r.case == case
                and (not story or r.story == story)]
        rows.sort(key=lambda r: (r.station, r.step_num or 0.0))
        return rows

    def frames_present(self) -> List[Tuple[str, str]]:
        """Pares (nivel, barra) con resultados, sin repetir."""
        seen: Dict[Tuple[str, str], None] = {}
        for r in self.frame_forces:
            seen.setdefault((r.story, r.frame), None)
        return list(seen)

    def envelope(self, story: str, frame: str, cases: Optional[Sequence[str]] = None
                 ) -> Dict[str, Optional[float]]:
        """Máximos y mínimos de M3/V2/P de una barra sobre los casos dados."""
        rows = [r for r in self.frame_forces
                if r.frame == frame and (not story or r.story == story)
                and (cases is None or r.case in cases)]
        out: Dict[str, Optional[float]] = {}
        for comp in ("M3", "V2", "P", "M2", "V3", "T"):
            vals = [getattr(r, comp) for r in rows if getattr(r, comp) is not None]
            out[f"{comp}_max"] = max(vals) if vals else None
            out[f"{comp}_min"] = min(vals) if vals else None
        return out


# ── Tablas planas (interfaz, CSV, XLSX, JSON) ───────────────────────────────

#: Definición de cada tipo de tabla: encabezados y extractor de renglón.
TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "frame_forces": {
        "title": "Elementos mecánicos (barras)",
        "columns": ["Nivel", "Barra", "Etiqueta", "Caso", "Paso", "N° paso",
                    "Estación", "P", "V2", "V3", "T", "M2", "M3"],
        "numeric_from": 5,
        "fields": ["story", "frame", "label", "case", "step_type", "step_num",
                   "station", "P", "V2", "V3", "T", "M2", "M3"],
        "attr": "frame_forces",
    },
    "displacements": {
        "title": "Desplazamientos de nudos",
        "columns": ["Nivel", "Nudo", "Etiqueta", "Caso", "Paso", "N° paso",
                    "U1", "U2", "U3", "R1", "R2", "R3"],
        "numeric_from": 5,
        "fields": ["story", "point", "label", "case", "step_type", "step_num",
                   "U1", "U2", "U3", "R1", "R2", "R3"],
        "attr": "displacements",
    },
    "drifts": {
        "title": "Derivas de entrepiso",
        "columns": ["Nivel", "Caso", "Paso", "Dirección", "Deriva", "Nudo",
                    "X", "Y", "Z"],
        "numeric_from": 4,
        "fields": ["story", "case", "step_type", "direction", "drift", "label",
                   "x", "y", "z"],
        "attr": "drifts",
    },
    "deflections": {
        "title": "Deflexiones de trabes (calculadas)",
        "columns": ["Nivel", "Barra", "Caso", "Estación", "Deflexión", "Claro",
                    "Máx."],
        "numeric_from": 3,
        "fields": ["story", "frame", "case", "station", "deflection", "span",
                   "is_max"],
        "attr": "deflections",
    },
    "reactions": {
        "title": "Reacciones en la base",
        "columns": ["Caso", "Paso", "FX", "FY", "FZ", "MX", "MY", "MZ"],
        "numeric_from": 2,
        "fields": ["case", "step_type", "FX", "FY", "FZ", "MX", "MY", "MZ"],
        "attr": "reactions",
    },
}


def table_rows(result: ResultSet, kind: str) -> List[List[Any]]:
    """Convierte una lista de resultados en renglones planos."""
    spec = TABLE_SPECS[kind]
    fields: Sequence[str] = spec["fields"]
    return [[getattr(row, f, None) for f in fields]
            for row in getattr(result, spec["attr"], [])]


def table_columns(kind: str, units: UnitSystem) -> List[str]:
    """Encabezados con la unidad de cada columna cuando aplica."""
    spec = TABLE_SPECS[kind]
    force, length, moment = units.force, units.length, units.moment
    suffix = {
        "P": force, "V2": force, "V3": force, "T": moment,
        "M2": moment, "M3": moment,
        "FX": force, "FY": force, "FZ": force,
        "MX": moment, "MY": moment, "MZ": moment,
        "Estación": length, "U1": length, "U2": length, "U3": length,
        "R1": "rad", "R2": "rad", "R3": "rad",
        "Deflexión": length, "Claro": length,
        "X": length, "Y": length, "Z": length,
    }
    return [f"{c} ({suffix[c]})" if c in suffix else c for c in spec["columns"]]


def to_dict(result: ResultSet) -> Dict[str, Any]:
    """Serializa un :class:`ResultSet` completo (para JSON)."""
    return {
        "source": result.source,
        "origin": result.origin,
        "units": asdict(result.units),
        "cases": result.cases,
        "stories": result.stories,
        "missing": result.missing,
        "warnings": result.warnings,
        "error": result.error,
        "tables": {
            kind: {
                "title": TABLE_SPECS[kind]["title"],
                "columns": table_columns(kind, result.units),
                "rows": table_rows(result, kind),
            }
            for kind in TABLE_SPECS
            if getattr(result, TABLE_SPECS[kind]["attr"], None)
        },
    }


def model_to_dict(model: StructuralModel) -> Dict[str, Any]:
    """Serializa la geometría (para JSON y para el puente del visor legado)."""
    return {
        "info": {
            "program": model.info.program,
            "version": model.info.version,
            "title": model.info.title,
            "file": model.info.file,
            "source": model.info.source,
            "units": model.info.units.label,
        },
        "stories": [asdict(s) for s in model.stories],
        "grids_x": [asdict(g) for g in model.grids_x],
        "grids_y": [asdict(g) for g in model.grids_y],
        "sections": {k: asdict(v) for k, v in model.sections.items()},
        "frames": [asdict(f) for f in model.frames],
        "load_patterns": model.load_patterns,
        "load_cases": model.load_cases,
        "load_combos": model.load_combos,
        "missing": model.missing,
        "warnings": model.warnings,
        "counts": model.counts(),
    }


def resolve_direction(xi: float, yi: float, zi: Optional[float],
                      xj: float, yj: float, zj: Optional[float],
                      tol: float = 1e-6) -> str:
    """Clasifica la barra por su orientación dominante."""
    dz = abs((zj or 0.0) - (zi or 0.0))
    dx, dy = abs(xj - xi), abs(yj - yi)
    if dz > tol and dx <= tol and dy <= tol:
        return "Z"
    if dy <= tol and dx > tol:
        return "X"
    if dx <= tol and dy > tol:
        return "Y"
    return "D"


def grid_label(grids: Iterable[GridLine], value: Optional[float],
               tol: float = 1e-6) -> Optional[str]:
    """Etiqueta del eje que coincide con la coordenada dada."""
    if value is None:
        return None
    for g in grids:
        if abs(g.ordinate - value) < tol:
            return g.label
    return None
