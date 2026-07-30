"""Lector de archivos de texto de ETABS (.e2k / .$et).

Es el camino que no necesita ETABS instalado: da toda la geometría (niveles,
ejes, nudos, secciones, barras y su asignación por nivel) y el catálogo de casos
y combinaciones. Un .e2k **no contiene resultados de análisis**, así que los
elementos mecánicos y las deformaciones se reportan como faltantes: se obtienen
por OAPI o importando la tabla exportada.

Portado del lector ``etabs_import.js`` del programa original, con estas mejoras:
las dimensiones de sección se convierten con las unidades declaradas en el
archivo (antes se asumía metros), se leen columnas y diagonales además de
trabes, y se resuelven cotas Z por nivel.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from .model import (
    FrameElement, GridLine, ModelInfo, Point, Section, Story, StructuralModel,
    grid_label, resolve_direction,
)
from .units import parse_units_label

_SECTION_HEADER = re.compile(r"^\s*\$")
_NUM = re.compile(r"^-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?$")

#: Firma mínima para aceptar el archivo como .e2k.
_SIGNATURE = re.compile(
    r"\$\s*(PROGRAM INFORMATION|CONTROLS|STORIES|GRID|POINT COORDINATES"
    r"|LINE CONNECTIVITIES)", re.IGNORECASE)


def _num(value: object) -> Optional[float]:
    """Convierte a float aceptando coma decimal; ``None`` si no es número."""
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not _NUM.match(text):
        try:
            parsed = float(text)
        except (TypeError, ValueError):
            return None
        return parsed
    return float(text)


def _quoted(line: str, key: str) -> Optional[str]:
    """Valor entre comillas de ``KEY "valor"``."""
    m = re.search(key + r'\s+"([^"]*)"', line, re.IGNORECASE)
    return m.group(1) if m else None


def _value(line: str, key: str) -> Optional[float]:
    """Valor numérico de ``KEY valor`` (sin comillas)."""
    m = re.search(key + r"\s+(-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)",
                  line, re.IGNORECASE)
    return _num(m.group(1)) if m else None


def section_dims_from_name(name: str) -> Optional[Tuple[float, float]]:
    """Deduce ``(b, h)`` en cm de nombres tipo ``V-30X70`` o ``30x70``.

    Se usa solo cuando el archivo no trae las dimensiones; el resultado se
    marca con ``dim_source='nombre'`` para que la interfaz lo advierta.
    """
    cleaned = re.sub(r"[^0-9Xx]", "", str(name or "")).upper()
    parts = cleaned.split("X")
    if len(parts) < 2:
        return None
    b, h = _num(parts[0]), _num(parts[1])
    if b is None or h is None or b <= 0 or h <= 0:
        return None
    return b, h


def parse_e2k(text: str, file_name: str = "") -> StructuralModel:
    """Interpreta el contenido de un .e2k / .$et y arma el modelo."""
    raw = text or ""
    model = StructuralModel(info=ModelInfo(source="e2k", file=file_name or ""))

    if not _SIGNATURE.search(raw):
        model.error = ("El archivo no tiene la estructura de un .e2k / .$et de "
                       "ETABS (no se encontró ninguna sección «$ …»).")
        return model

    section = ""
    stories_top_down: List[Dict[str, Optional[float]]] = []
    connectivity: List[Dict[str, object]] = []
    assigns: List[Dict[str, object]] = []
    section_lines: Dict[str, Dict[str, Optional[str]]] = {}

    for line in raw.splitlines():
        if _SECTION_HEADER.match(line):
            section = re.sub(r"^\s*\$\s*", "", line).strip().upper()
            continue
        if not line.strip():
            continue

        if "PROGRAM INFORMATION" in section:
            model.info.program = _quoted(line, "PROGRAM") or model.info.program
            model.info.version = _quoted(line, "VERSION") or model.info.version

        elif "CONTROLS" in section:
            m = re.search(r'UNITS\s+"([^"]*)"\s+"([^"]*)"(?:\s+"([^"]*)")?',
                          line, re.IGNORECASE)
            if m:
                label = ", ".join([p for p in m.groups() if p])
                model.info.units = parse_units_label(label)
            title = _quoted(line, "TITLE1")
            if title:
                model.info.title = title

        elif "STORIES" in section:
            name = _quoted(line, "STORY")
            if name is None:
                continue
            stories_top_down.append({
                "name": name,
                "height": _value(line, "HEIGHT"),
                "elev": _value(line, "ELEV"),
            })

        elif "GRID" in section:
            label = _quoted(line, "LABEL")
            if label is None:
                continue
            direction = (_quoted(line, "DIR") or "").upper()
            ordinate = _value(line, "COORD")
            if ordinate is None:
                ordinate = _value(line, "ORDINATE")
            if ordinate is None:
                continue
            if direction == "X":
                model.grids_x.append(GridLine(label, "X", ordinate))
            elif direction == "Y":
                model.grids_y.append(GridLine(label, "Y", ordinate))

        elif "FRAME SECTIONS" in section:
            name = _quoted(line, "FRAMESECTION")
            if name is None:
                continue
            section_lines[name] = {
                "material": _quoted(line, "MATERIAL"),
                "shape": _quoted(line, "SHAPE"),
                "d": _value(line, r"\bD"),
                "b": _value(line, r"\bB"),
            }

        elif "POINT COORDINATES" in section:
            m = re.search(
                r'POINT\s+"([^"]*)"\s+(-?[0-9.eE+-]+)\s+(-?[0-9.eE+-]+)'
                r"(?:\s+(-?[0-9.eE+-]+))?", line, re.IGNORECASE)
            if m:
                x, y = _num(m.group(2)), _num(m.group(3))
                if x is None or y is None:
                    continue
                model.points[m.group(1)] = Point(m.group(1), x, y, _num(m.group(4)))

        elif "LINE CONNECTIVITIES" in section:
            m = re.search(
                r'LINE\s+"([^"]*)"\s+(BEAM|COLUMN|BRACE)\s+"([^"]*)"\s+"([^"]*)"'
                r"(?:\s+(-?[0-9]+))?", line, re.IGNORECASE)
            if m:
                connectivity.append({
                    "id": m.group(1),
                    "kind": m.group(2).upper(),
                    "i": m.group(3),
                    "j": m.group(4),
                    "span": int(m.group(5)) if m.group(5) else 0,
                })

        elif "LINE ASSIGNS" in section:
            m = re.search(r'LINEASSIGN\s+"([^"]*)"\s+"([^"]*)"', line, re.IGNORECASE)
            if m:
                assigns.append({
                    "id": m.group(1),
                    "story": m.group(2),
                    "section": _quoted(line, "SECTION"),
                })

        elif "LOAD PATTERNS" in section:
            name = _quoted(line, "LOADPATTERN")
            if name and name not in model.load_patterns:
                model.load_patterns.append(name)

        elif "LOAD CASES" in section:
            name = _quoted(line, "LOADCASE")
            if name and name not in model.load_cases:
                model.load_cases.append(name)

        elif "LOAD COMBINATIONS" in section:
            name = _quoted(line, "COMBO")
            if name and name not in model.load_combos:
                model.load_combos.append(name)

    _resolve_stories(model, stories_top_down)
    _resolve_sections(model, section_lines)
    _resolve_frames(model, connectivity, assigns)
    _report_gaps(model)
    return model


# ── etapas de resolución ────────────────────────────────────────────────────


def _resolve_stories(model: StructuralModel,
                     stories_top_down: List[Dict[str, Optional[float]]]) -> None:
    """Convierte la lista «de arriba hacia abajo» con HEIGHT en cotas absolutas.

    Se conservan **todos** los niveles, incluidos la base y los sótanos con cota
    negativa; el nivel base es el último del archivo y su ELEV es el origen.
    """
    if not stories_top_down:
        return
    base = stories_top_down[-1]
    z = base.get("elev")
    z = float(z) if z is not None else 0.0
    resolved: List[Story] = []
    for index in range(len(stories_top_down) - 1, -1, -1):
        item = stories_top_down[index]
        height = item.get("height")
        name = str(item["name"])
        if height is None:
            elev = item.get("elev")
            resolved.insert(0, Story(name, elevation=float(elev) if elev is not None else z,
                                     height=None, is_base=True))
            continue
        z += float(height)
        resolved.insert(0, Story(name, elevation=round(z, 6), height=float(height)))
    model.stories = resolved


def _resolve_sections(model: StructuralModel,
                      section_lines: Dict[str, Dict[str, Optional[str]]]) -> None:
    """Pasa D/B a centímetros usando las unidades declaradas en el archivo."""
    to_cm = model.info.units.length_to_cm
    for name, data in section_lines.items():
        h = data.get("d")
        b = data.get("b")
        source: Optional[str] = None
        if h is not None and b is not None:
            h, b, source = float(h) * to_cm, float(b) * to_cm, "e2k"
        else:
            guessed = section_dims_from_name(name)
            if guessed:
                b, h, source = guessed[0], guessed[1], "nombre"
                model.warnings.append(
                    f"La sección «{name}» no trae dimensiones: se dedujeron "
                    f"{b:g}×{h:g} cm de su nombre.")
            else:
                model.warnings.append(
                    f"No se pudieron leer las dimensiones de la sección «{name}».")
                b = h = None
        model.sections[name] = Section(
            name=name,
            material=data.get("material"),      # type: ignore[arg-type]
            shape=data.get("shape"),            # type: ignore[arg-type]
            b_cm=b, h_cm=h, dim_source=source)


def _resolve_frames(model: StructuralModel, connectivity: List[Dict[str, object]],
                    assigns: List[Dict[str, object]]) -> None:
    """Cruza conectividad, coordenadas y asignaciones para armar las barras."""
    elevation = {s.name: s.elevation for s in model.stories}
    order = {s.name: i for i, s in enumerate(model.stories)}   # 0 = nivel más alto
    conn = {str(c["id"]): c for c in connectivity}

    for assign in assigns:
        line_id = str(assign["id"])
        c = conn.get(line_id)
        if c is None:
            model.warnings.append(
                f"La asignación de «{line_id}» no tiene conectividad declarada.")
            continue
        pi = model.points.get(str(c["i"]))
        pj = model.points.get(str(c["j"]))
        if pi is None or pj is None:
            model.warnings.append(
                f"La línea {line_id} referencia un punto inexistente.")
            continue

        story = str(assign["story"])
        z_top = elevation.get(story)
        z_i, z_j = z_top, z_top
        kind = str(c["kind"])
        if kind in ("COLUMN", "BRACE"):
            spans = int(c["span"] or 1) or 1
            index = order.get(story)
            if index is not None and index + spans < len(model.stories):
                z_j = model.stories[index + spans].elevation
            elif z_top is not None:
                z_j = None       # el nivel inferior no está en el archivo

        frame = FrameElement(
            name=line_id, label=line_id, story=story, kind=kind,
            section=assign.get("section"),      # type: ignore[arg-type]
            point_i=pi.name, point_j=pj.name,
            xi=pi.x, yi=pi.y, zi=z_i, xj=pj.x, yj=pj.y, zj=z_j)
        frame.direction = resolve_direction(pi.x, pi.y, z_i, pj.x, pj.y, z_j)
        if frame.direction == "X":
            frame.grid_line = grid_label(model.grids_y, pi.y)
            frame.grid_i = grid_label(model.grids_x, min(pi.x, pj.x))
            frame.grid_j = grid_label(model.grids_x, max(pi.x, pj.x))
        elif frame.direction == "Y":
            frame.grid_line = grid_label(model.grids_x, pi.x)
            frame.grid_i = grid_label(model.grids_y, min(pi.y, pj.y))
            frame.grid_j = grid_label(model.grids_y, max(pi.y, pj.y))
        else:
            frame.grid_i = grid_label(model.grids_x, pi.x)
            frame.grid_j = grid_label(model.grids_y, pi.y)
        model.frames.append(frame)

    assigned = {f.name for f in model.frames}
    orphans = [k for k in conn if k not in assigned]
    if orphans:
        model.warnings.append(
            f"{len(orphans)} línea(s) sin asignación de nivel ($ LINE ASSIGNS): "
            "no se pueden ubicar en la estructura.")


def _report_gaps(model: StructuralModel) -> None:
    """Deja constancia de lo que el archivo no contiene."""
    if not model.stories:
        model.missing.append("Niveles ($ STORIES)")
    if not model.grids_x or not model.grids_y:
        model.missing.append("Ejes en ambas direcciones ($ GRIDS)")
    if not model.points:
        model.missing.append("Coordenadas de nudos ($ POINT COORDINATES)")
    if not model.frames:
        model.missing.append("Barras asignadas a niveles ($ LINE ASSIGNS)")
    if not model.sections:
        model.missing.append("Secciones ($ FRAME SECTIONS)")
    model.missing.append(
        "Elementos mecánicos y deformaciones — un .e2k no contiene resultados "
        "de análisis: conéctate a ETABS o importa la tabla exportada")

    if not model.frames and model.error is None:
        model.error = ("El archivo se leyó pero no contiene barras asignadas a "
                       "niveles.")


def parse_e2k_file(path: str, encoding: Optional[str] = None) -> StructuralModel:
    """Lee un .e2k/.$et del disco tolerando codificaciones heredadas."""
    encodings = [encoding] if encoding else ["utf-8-sig", "utf-8", "latin-1"]
    last_error: Optional[Exception] = None
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as handle:
                text = handle.read()
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        return parse_e2k(text, os.path.basename(path))
    raise UnicodeDecodeError(  # pragma: no cover - solo si fallan todas
        "e2k", b"", 0, 1, f"No se pudo decodificar {path}: {last_error}")
