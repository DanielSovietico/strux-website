"""Puente con el visor original (``legacy/Vigas_ETABS_autocontenido.html``).

El programa del que nació esta aplicación ya esperaba un puente de escritorio
con dos ranuras, ``etabs_model`` y ``etabs_frame_forces`` (ver
``legacy/etabs_import.js``). Aquí se generan exactamente esas dos cargas útiles
a partir del modelo y los resultados extraídos, de modo que el visor de vigas
siga sirviendo sin cambiarle una línea: se guarda el JSON y se carga desde el
visor, o se responde con él si algún día se hospeda el HTML en una ventana web.

Formato esperado por el visor (``fromOapiModel`` y ``fromOapiFrameForce``):

``etabs_model``
    ``{program, version, units, title, file, stories:[{name,height,elev}],
    gx:[[label,coord]], gy:[[label,coord]],
    sections:{nombre:{b,h,mat,shape}},
    beams:[{id,story,section,xi,yi,xj,yj}], cases:[...]}``

``etabs_frame_forces``
    ``{frames:[{name,story,station:[],loadCase:[],p:[],v2:[],m3:[]}]}``
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from .model import ResultSet, StructuralModel


def model_payload(model: StructuralModel) -> Dict[str, Any]:
    """Carga útil de la ranura ``etabs_model``."""
    return {
        "program": model.info.program or "ETABS",
        "version": model.info.version,
        "units": model.info.units.label,
        "title": model.info.title,
        "file": model.info.file or "modelo abierto en ETABS",
        "stories": [
            {"name": s.name, "height": s.height, "elev": s.elevation,
             "base": s.is_base}
            for s in model.stories
        ],
        "gx": [[g.label, g.ordinate] for g in model.grids_x],
        "gy": [[g.label, g.ordinate] for g in model.grids_y],
        "sections": {
            name: {"b": section.b_cm, "h": section.h_cm,
                   "mat": section.material, "shape": section.shape}
            for name, section in model.sections.items()
        },
        "beams": [
            {"id": f.name, "story": f.story, "section": f.section,
             "xi": f.xi, "yi": f.yi, "xj": f.xj, "yj": f.yj}
            for f in model.beams()
            if None not in (f.xi, f.yi, f.xj, f.yj)
        ],
        "cases": model.all_cases,
    }


def frame_forces_payload(result: ResultSet, story: Optional[str] = None,
                         frames: Optional[Sequence[str]] = None,
                         cases: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Carga útil de la ranura ``etabs_frame_forces``."""
    wanted_frames = set(frames) if frames else None
    wanted_cases = set(cases) if cases else None
    grouped: Dict[str, Dict[str, Any]] = {}

    for row in result.frame_forces:
        if story and row.story != story:
            continue
        if wanted_frames is not None and row.frame not in wanted_frames:
            continue
        if wanted_cases is not None and row.case not in wanted_cases:
            continue
        entry = grouped.setdefault(f"{row.story}|{row.frame}", {
            "name": row.frame, "story": row.story,
            "station": [], "loadCase": [], "p": [], "v2": [], "m3": [],
        })
        entry["station"].append(row.station)
        entry["loadCase"].append(row.case)
        entry["p"].append(row.P if row.P is not None else 0.0)
        entry["v2"].append(row.V2 if row.V2 is not None else 0.0)
        entry["m3"].append(row.M3 if row.M3 is not None else 0.0)

    return {"frames": list(grouped.values())}


def write_bridge_json(path: str, model: Optional[StructuralModel],
                      result: Optional[ResultSet]) -> str:
    """Guarda las dos cargas útiles en un solo archivo JSON."""
    payload: Dict[str, Any] = {}
    if model is not None:
        payload["etabs_model"] = model_payload(model)
    if result is not None:
        payload["etabs_frame_forces"] = frame_forces_payload(result)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path
