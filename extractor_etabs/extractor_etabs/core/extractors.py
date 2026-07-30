"""Extracción de geometría y resultados desde una conexión con ETABS.

Aquí vive la traducción entre la OAPI y el modelo de datos de la aplicación, más
la parte que no depende de la fuente: el cálculo de deflexiones, que también
funciona con tablas importadas.

Dos decisiones pensadas para modelos grandes:

* la lectura de barras y de resultados avisa su avance y **se puede cancelar**
  (el callback de progreso devuelve ``False`` para abortar);
* cuando se piden muchas barras se intenta una sola llamada por grupo (``All``)
  en lugar de una llamada por barra, que es lo que vuelve inviable un modelo de
  miles de elementos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import deflection as defl
from .e2k_parser import section_dims_from_name
from .etabs_api import (
    ITEM_GROUP_ELM, ITEM_OBJECT_ELM, EtabsConnection, EtabsError,
)
from .model import (
    DeflectionRow, DriftRow, FrameElement, FrameForceRow, GridLine,
    JointDisplRow, ModelInfo, ReactionRow, ResultSet, Section, Story,
    StructuralModel, grid_label, resolve_direction,
)
from .units import UnitSystem, unit_system

#: ``(mensaje, hechos, total) -> seguir``. Devolver ``False`` cancela.
Progress = Callable[[str, int, int], bool]

#: Grupo que ETABS crea por omisión con todos los objetos del modelo.
ALL_GROUP = "All"

#: A partir de cuántos elementos conviene pedir por grupo en vez de uno por uno.
GROUP_THRESHOLD = 25


class Cancelled(Exception):
    """El usuario canceló la operación."""


def _tick(progress: Optional[Progress], message: str, done: int, total: int) -> None:
    if progress is None:
        return
    if progress(message, done, total) is False:
        raise Cancelled(message)


@dataclass
class ExtractionOptions:
    """Qué extraer y con qué criterios."""

    cases: List[str] = field(default_factory=list)
    combos: List[str] = field(default_factory=list)
    frame_forces: bool = True
    displacements: bool = True
    drifts: bool = True
    reactions: bool = False
    deflections: bool = False
    stories: List[str] = field(default_factory=list)      # vacío = todos
    frames: List[str] = field(default_factory=list)       # vacío = según niveles
    kinds: List[str] = field(default_factory=lambda: ["BEAM", "COLUMN", "BRACE"])
    units_key: str = "Ton_m_C"
    e_value: float = 221359.0        # kgf/cm² ≈ concreto clase 1, f'c = 250
    e_units: str = "kgf/cm2"
    inertia_factor: float = 1.0
    run_analysis_if_unlocked: bool = False

    @property
    def all_case_names(self) -> List[str]:
        seen: Dict[str, None] = {}
        for name in list(self.cases) + list(self.combos):
            seen.setdefault(name, None)
        return list(seen)

    def wants_anything(self) -> bool:
        return any((self.frame_forces, self.displacements, self.drifts,
                    self.reactions, self.deflections))


# ── geometría por OAPI ──────────────────────────────────────────────────────


class ModelReader:
    """Arma un :class:`StructuralModel` desde el modelo abierto en ETABS."""

    def __init__(self, connection: EtabsConnection) -> None:
        self.conn = connection

    def read(self, units_key: str = "Ton_m_C",
             progress: Optional[Progress] = None,
             kinds: Optional[Sequence[str]] = None) -> StructuralModel:
        conn = self.conn
        conn.warnings.clear()
        units = unit_system(units_key)
        if units.etabs_code:
            conn.set_units(units.etabs_code)

        info = conn.program_info()
        filename = conn.model_filename()
        model = StructuralModel(info=ModelInfo(
            program=info.name, version=info.version, units=units,
            file=filename, title=filename, source="oapi"))

        _tick(progress, "Leyendo niveles…", 0, 100)
        for name, elevation, height in conn.stories():
            model.stories.append(Story(name=name, elevation=elevation,
                                       height=height))
        # ETABS entrega los niveles de abajo hacia arriba; la interfaz los
        # muestra como en el programa: del más alto al más bajo.
        model.stories.sort(key=lambda s: (s.elevation is None, -(s.elevation or 0.0)))
        if model.stories:
            model.stories[-1].is_base = model.stories[-1].height in (None, 0)

        _tick(progress, "Leyendo ejes…", 5, 100)
        gx, gy = conn.grid_lines()
        model.grids_x = [GridLine(label, "X", ordinate) for label, ordinate in gx]
        model.grids_y = [GridLine(label, "Y", ordinate) for label, ordinate in gy]

        _tick(progress, "Leyendo casos de carga…", 10, 100)
        model.load_patterns = conn.load_patterns()
        model.load_cases = conn.load_cases()
        model.load_combos = conn.load_combos()

        _tick(progress, "Leyendo secciones…", 14, 100)
        self._read_sections(model)

        names = conn.frame_names()
        wanted = set(kinds) if kinds else None
        total = len(names) or 1
        for index, name in enumerate(names):
            if index % 25 == 0:
                _tick(progress, f"Leyendo barras… ({index}/{len(names)})",
                      20 + int(70 * index / total), 100)
            try:
                data = conn.frame_geometry(name)
            except EtabsError as exc:
                model.warnings.append(str(exc))
                continue
            frame = self._to_frame(model, data)
            if wanted and frame.kind not in wanted:
                continue
            model.frames.append(frame)

        _tick(progress, "Modelo leído", 95, 100)
        model.warnings.extend(conn.warnings)
        self._report_gaps(model)
        return model

    def _read_sections(self, model: StructuralModel) -> None:
        conn = self.conn
        for name in conn.section_names():
            data = conn.rectangular_section(name)
            if data:
                to_cm = model.info.units.length_to_cm
                model.sections[name] = Section(
                    name=name, material=data["material"], shape=data["shape"],
                    b_cm=data["b"] * to_cm, h_cm=data["h"] * to_cm,
                    dim_source="api")
                continue
            guessed = section_dims_from_name(name)
            if guessed:
                model.sections[name] = Section(
                    name=name, b_cm=guessed[0], h_cm=guessed[1],
                    dim_source="nombre")
                model.warnings.append(
                    f"La sección «{name}» no es rectangular en ETABS: se "
                    f"dedujeron {guessed[0]:g}×{guessed[1]:g} cm de su nombre.")
            else:
                model.sections[name] = Section(name=name)
                model.warnings.append(
                    f"No se pudieron obtener las dimensiones de la sección "
                    f"«{name}»: las deflexiones de sus barras no se calcularán.")

    def _to_frame(self, model: StructuralModel, data: Dict[str, object]
                  ) -> FrameElement:
        frame = FrameElement(
            name=str(data.get("name")),
            label=data.get("label"),            # type: ignore[arg-type]
            story=data.get("story"),            # type: ignore[arg-type]
            section=data.get("section"),        # type: ignore[arg-type]
            kind=str(data.get("kind") or "OTHER"),
            point_i=data.get("point_i"),        # type: ignore[arg-type]
            point_j=data.get("point_j"),        # type: ignore[arg-type]
            xi=data.get("xi"), yi=data.get("yi"), zi=data.get("zi"),  # type: ignore[arg-type]
            xj=data.get("xj"), yj=data.get("yj"), zj=data.get("zj"),  # type: ignore[arg-type]
        )
        if None not in (frame.xi, frame.yi, frame.xj, frame.yj):
            frame.direction = resolve_direction(
                frame.xi, frame.yi, frame.zi, frame.xj, frame.yj, frame.zj)  # type: ignore[arg-type]
            if frame.direction == "X":
                frame.grid_line = grid_label(model.grids_y, frame.yi)
                frame.grid_i = grid_label(model.grids_x, min(frame.xi, frame.xj))
                frame.grid_j = grid_label(model.grids_x, max(frame.xi, frame.xj))
            elif frame.direction == "Y":
                frame.grid_line = grid_label(model.grids_x, frame.xi)
                frame.grid_i = grid_label(model.grids_y, min(frame.yi, frame.yj))
                frame.grid_j = grid_label(model.grids_y, max(frame.yi, frame.yj))
        return frame

    def _report_gaps(self, model: StructuralModel) -> None:
        if not model.stories:
            model.missing.append("Niveles (Story data)")
        if not model.grids_x or not model.grids_y:
            model.missing.append("Ordenadas de ejes en ambas direcciones")
        if not model.frames:
            model.error = "ETABS respondió sin barras en el modelo."
        locked = self.conn.is_locked()
        if locked is False:
            model.missing.append(
                "Resultados de análisis — el modelo no está bloqueado, es decir "
                "el análisis no está corrido")


# ── resultados por OAPI ─────────────────────────────────────────────────────


class ResultsReader:
    """Extrae elementos mecánicos, desplazamientos, derivas y reacciones."""

    def __init__(self, connection: EtabsConnection) -> None:
        self.conn = connection

    def extract(self, model: StructuralModel, options: ExtractionOptions,
                progress: Optional[Progress] = None) -> ResultSet:
        conn = self.conn
        conn.warnings.clear()
        units = unit_system(options.units_key)
        if units.etabs_code:
            conn.set_units(units.etabs_code)

        result = ResultSet(source="oapi", units=units,
                           origin=conn.model_filename() or "modelo abierto en ETABS")

        if not options.wants_anything():
            result.error = "No se seleccionó ninguna cantidad para extraer."
            return result
        if not options.all_case_names:
            result.error = ("No se seleccionó ningún caso de carga ni "
                            "combinación.")
            return result

        if conn.is_locked() is False:
            if options.run_analysis_if_unlocked:
                _tick(progress, "Corriendo el análisis en ETABS…", 0, 100)
                conn.run_analysis()
            else:
                result.error = (
                    "El modelo no tiene el análisis corrido: ETABS no puede "
                    "entregar resultados. Córrelo en ETABS (o activa «correr el "
                    "análisis si hace falta») y vuelve a extraer.")
                return result

        _tick(progress, "Seleccionando casos de salida…", 2, 100)
        accepted = conn.select_output(options.cases, options.combos)
        if not accepted:
            result.error = ("ETABS no aceptó ninguno de los casos seleccionados. "
                            "Verifica que existan en el modelo.")
            result.warnings.extend(conn.warnings)
            return result
        result.cases = list(accepted)

        frames = self._target_frames(model, options)
        if options.frame_forces:
            self._read_frame_forces(result, model, frames, progress)
        if options.displacements:
            self._read_displacements(result, model, options, progress)
        if options.drifts:
            self._read_drifts(result, progress)
        if options.reactions:
            self._read_reactions(result, progress)
        if options.deflections:
            _tick(progress, "Calculando deflexiones…", 92, 100)
            compute_deflections(result, model, options)

        result.stories = sorted({r.story for r in result.frame_forces if r.story}
                                | {r.story for r in result.displacements if r.story}
                                | {r.story for r in result.drifts if r.story})
        result.warnings.extend(conn.warnings)
        if result.row_count == 0 and result.error is None:
            result.error = (
                "ETABS no devolvió resultados para lo solicitado. Revisa que "
                "los casos estén seleccionados para salida en el modelo y que "
                "el análisis corresponda al estado actual.")
        _tick(progress, "Listo", 100, 100)
        return result

    # ── selección de barras ──
    def _target_frames(self, model: StructuralModel,
                       options: ExtractionOptions) -> List[FrameElement]:
        frames = model.frames
        if options.frames:
            wanted = set(options.frames)
            return [f for f in frames if f.name in wanted or f.label in wanted]
        selected = [f for f in frames if f.kind in options.kinds]
        if options.stories:
            stories = set(options.stories)
            selected = [f for f in selected if f.story in stories]
        return selected

    # ── fuerzas ──
    def _read_frame_forces(self, result: ResultSet, model: StructuralModel,
                           frames: Sequence[FrameElement],
                           progress: Optional[Progress]) -> None:
        if not frames:
            result.warnings.append(
                "No hay barras que cumplan el filtro de niveles y tipos, así "
                "que no se pidieron elementos mecánicos.")
            return

        wanted = {f.name for f in frames}
        meta = {f.name: f for f in model.frames}

        if len(frames) >= GROUP_THRESHOLD:
            _tick(progress, "Pidiendo fuerzas de todas las barras…", 6, 100)
            rows = self._forces_by_group(meta, wanted)
            if rows is not None:
                result.frame_forces.extend(rows)
                return

        total = len(frames)
        for index, frame in enumerate(frames):
            if index % 10 == 0:
                _tick(progress, f"Fuerzas… ({index}/{total})",
                      6 + int(60 * index / max(total, 1)), 100)
            try:
                data = self.conn.frame_force(frame.name, ITEM_OBJECT_ELM)
            except EtabsError as exc:
                result.warnings.append(str(exc))
                continue
            result.frame_forces.extend(
                self._forces_to_rows(data, meta, {frame.name}))

    def _forces_by_group(self, meta: Dict[str, FrameElement],
                         wanted: set) -> Optional[List[FrameForceRow]]:
        """Una sola llamada para todo el modelo; ``None`` si ETABS la rechaza."""
        try:
            data = self.conn.frame_force(ALL_GROUP, ITEM_GROUP_ELM)
        except EtabsError as exc:
            self.conn.warnings.append(
                f"No se pudo usar el grupo «{ALL_GROUP}» ({exc}); se piden las "
                "barras una por una.")
            return None
        return self._forces_to_rows(data, meta, wanted)

    @staticmethod
    def _forces_to_rows(data: Dict[str, List[object]],
                        meta: Dict[str, FrameElement],
                        wanted: Optional[set]) -> List[FrameForceRow]:
        rows: List[FrameForceRow] = []
        objects = [str(o) for o in data.get("obj", [])]
        for i, name in enumerate(objects):
            if wanted is not None and name not in wanted:
                continue
            frame = meta.get(name)

            def value(key: str) -> Optional[float]:
                column = data.get(key) or []
                if i >= len(column) or column[i] is None:
                    return None
                return float(column[i])       # type: ignore[arg-type]

            station = value("obj_sta")
            if station is None:
                station = value("elm_sta") or 0.0
            cases = data.get("case") or []
            steps = data.get("step_type") or []
            rows.append(FrameForceRow(
                story=(frame.story if frame else "") or "",
                frame=name,
                label=frame.label if frame else None,
                case=str(cases[i]) if i < len(cases) else "",
                step_type=str(steps[i]) if i < len(steps) and steps[i] else None,
                step_num=value("step_num"),
                station=station,
                P=value("P"), V2=value("V2"), V3=value("V3"),
                T=value("T"), M2=value("M2"), M3=value("M3")))
        return rows

    # ── desplazamientos ──
    def _read_displacements(self, result: ResultSet, model: StructuralModel,
                            options: ExtractionOptions,
                            progress: Optional[Progress]) -> None:
        _tick(progress, "Pidiendo desplazamientos de nudos…", 70, 100)
        story_of: Dict[str, str] = {}
        for frame in model.frames:
            for point in (frame.point_i, frame.point_j):
                if point and frame.story:
                    story_of.setdefault(point, frame.story)

        data: Optional[Dict[str, List[object]]] = None
        try:
            data = self.conn.joint_displacements(ALL_GROUP, ITEM_GROUP_ELM)
        except EtabsError as exc:
            self.conn.warnings.append(
                f"No se pudo pedir el grupo «{ALL_GROUP}» ({exc}); se piden los "
                "nudos de los niveles seleccionados.")

        if data is None:
            points: List[str] = []
            for story in (options.stories or model.story_names()):
                points.extend(self.conn.point_names_for_story(story))
            total = len(points) or 1
            for index, point in enumerate(points):
                if index % 20 == 0:
                    _tick(progress, f"Desplazamientos… ({index}/{total})",
                          70 + int(15 * index / total), 100)
                try:
                    single = self.conn.joint_displacements(point, ITEM_OBJECT_ELM)
                except EtabsError as exc:
                    result.warnings.append(str(exc))
                    continue
                result.displacements.extend(
                    self._displ_to_rows(single, story_of, options))
            return

        result.displacements.extend(self._displ_to_rows(data, story_of, options))

    @staticmethod
    def _displ_to_rows(data: Dict[str, List[object]], story_of: Dict[str, str],
                       options: ExtractionOptions) -> List[JointDisplRow]:
        rows: List[JointDisplRow] = []
        objects = [str(o) for o in data.get("obj", [])]
        stories = set(options.stories)
        for i, point in enumerate(objects):
            story = story_of.get(point)
            if stories and story not in stories:
                continue

            def value(key: str) -> Optional[float]:
                column = data.get(key) or []
                if i >= len(column) or column[i] is None:
                    return None
                return float(column[i])       # type: ignore[arg-type]

            cases = data.get("case") or []
            steps = data.get("step_type") or []
            rows.append(JointDisplRow(
                story=story, point=point, label=None,
                case=str(cases[i]) if i < len(cases) else "",
                step_type=str(steps[i]) if i < len(steps) and steps[i] else None,
                step_num=value("step_num"),
                U1=value("U1"), U2=value("U2"), U3=value("U3"),
                R1=value("R1"), R2=value("R2"), R3=value("R3")))
        return rows

    # ── derivas y reacciones ──
    def _read_drifts(self, result: ResultSet,
                     progress: Optional[Progress]) -> None:
        _tick(progress, "Pidiendo derivas de entrepiso…", 86, 100)
        try:
            data = self.conn.story_drifts()
        except EtabsError as exc:
            result.warnings.append(str(exc))
            result.missing.append("Derivas de entrepiso (Results.StoryDrifts)")
            return
        stories = [str(s) for s in data.get("story", [])]
        for i, story in enumerate(stories):
            def value(key: str) -> Optional[float]:
                column = data.get(key) or []
                if i >= len(column) or column[i] is None:
                    return None
                return float(column[i])       # type: ignore[arg-type]

            def text(key: str) -> Optional[str]:
                column = data.get(key) or []
                return str(column[i]) if i < len(column) and column[i] else None

            result.drifts.append(DriftRow(
                story=story, case=text("case") or "", step_type=text("step_type"),
                direction=text("direction"), drift=value("drift"),
                label=text("label"), x=value("x"), y=value("y"), z=value("z")))

    def _read_reactions(self, result: ResultSet,
                        progress: Optional[Progress]) -> None:
        _tick(progress, "Pidiendo reacciones en la base…", 90, 100)
        try:
            data = self.conn.base_reactions()
        except EtabsError as exc:
            result.warnings.append(str(exc))
            result.missing.append("Reacciones en la base (Results.BaseReact)")
            return
        cases = [str(c) for c in data.get("case", [])]
        for i, case in enumerate(cases):
            def value(key: str) -> Optional[float]:
                column = data.get(key) or []
                if i >= len(column) or column[i] is None:
                    return None
                return float(column[i])       # type: ignore[arg-type]

            steps = data.get("step_type") or []
            result.reactions.append(ReactionRow(
                case=case,
                step_type=str(steps[i]) if i < len(steps) and steps[i] else None,
                FX=value("FX"), FY=value("FY"), FZ=value("FZ"),
                MX=value("MX"), MY=value("MY"), MZ=value("MZ")))


# ── deflexiones (sirve para OAPI y para tablas importadas) ──────────────────


def compute_deflections(result: ResultSet, model: StructuralModel,
                        options: ExtractionOptions,
                        progress: Optional[Progress] = None) -> int:
    """Agrega al ``ResultSet`` la curva de deflexión de cada trabe y caso.

    Devuelve cuántas curvas se calcularon. Cada barra sin sección legible o con
    muy pocas estaciones se anota en ``warnings`` en lugar de inventarse.
    """
    if not result.frame_forces:
        result.missing.append(
            "Deflexiones — se calculan de M3, y no hay elementos mecánicos")
        return 0

    frames = {f.name: f for f in model.frames}
    by_label = {f.label: f for f in model.frames if f.label}
    ends_u3 = _joint_u3_lookup(result)

    groups: Dict[Tuple[str, str, str], List[FrameForceRow]] = {}
    for row in result.frame_forces:
        groups.setdefault((row.story, row.frame, row.case), []).append(row)

    computed = 0
    skipped_sections: set = set()
    total = len(groups) or 1
    for index, ((story, name, case), rows) in enumerate(sorted(groups.items())):
        if index % 50 == 0:
            _tick(progress, f"Deflexiones… ({index}/{total})", index, total)
        frame = frames.get(name) or by_label.get(name)
        if frame is None or frame.kind != "BEAM":
            continue
        section = model.sections.get(frame.section or "")
        ei = defl.section_ei(section, result.units, options.e_value,
                             options.e_units, options.inertia_factor)
        if ei is None:
            skipped_sections.add(frame.section or f"(sin sección) {name}")
            continue

        delta_i = ends_u3.get((case, frame.point_i or ""), 0.0)
        delta_j = ends_u3.get((case, frame.point_j or ""), 0.0)
        curve = defl.deflection_from_moments(
            [r.station for r in rows], [r.M3 for r in rows], ei,
            delta_i=delta_i, delta_j=delta_j)
        if not curve.values:
            if curve.note:
                result.warnings.append(f"{name} · {case}: {curve.note}")
            continue
        computed += 1
        peak_station = curve.max_station
        for station, value in zip(curve.stations, curve.values):
            result.deflections.append(DeflectionRow(
                story=story, frame=name, case=case, station=station,
                deflection=value, span=curve.span,
                is_max=abs(station - peak_station) < 1e-9))

    if skipped_sections:
        result.warnings.append(
            "Sin deflexión por falta de dimensiones de sección: "
            + ", ".join(sorted(skipped_sections)[:8])
            + (" …" if len(skipped_sections) > 8 else ""))
    if computed:
        result.warnings.append(
            f"Deflexiones calculadas por doble integración de M3/EI en "
            f"{computed} claro(s), con E = {options.e_value:g} "
            f"{options.e_units} e inercia × {options.inertia_factor:g}. "
            "Son un cálculo de esta aplicación, no una lectura de ETABS.")
    return computed


def _joint_u3_lookup(result: ResultSet) -> Dict[Tuple[str, str], float]:
    """``(caso, nudo) → U3`` hacia abajo positivo, para las fronteras."""
    lookup: Dict[Tuple[str, str], float] = {}
    for row in result.displacements:
        if row.U3 is None:
            continue
        key = (row.case, row.point)
        # Con varios pasos se conserva el más desfavorable (mayor magnitud).
        current = lookup.get(key)
        candidate = -float(row.U3)          # U3 positivo hacia arriba en ETABS
        if current is None or abs(candidate) > abs(current):
            lookup[key] = candidate
    return lookup
