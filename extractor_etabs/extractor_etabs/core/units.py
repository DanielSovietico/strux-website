"""Unidades: enumeración de la OAPI de ETABS y conversiones auxiliares.

La OAPI entrega todos los resultados en las *unidades presentes* del modelo, así
que la aplicación fija explícitamente el sistema antes de leer y guarda la
etiqueta correspondiente junto con los datos. Así una tabla exportada nunca
queda sin referencia de unidades.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# ── eUnits de la OAPI (ETABSv1.eUnits) ──────────────────────────────────────
# El valor entero es el que espera SapModel.SetPresentUnits().
E_UNITS: Dict[str, int] = {
    "lb_in_F": 1,
    "lb_ft_F": 2,
    "kip_in_F": 3,
    "kip_ft_F": 4,
    "kN_mm_C": 5,
    "kN_m_C": 6,
    "kgf_mm_C": 7,
    "kgf_m_C": 8,
    "N_mm_C": 9,
    "N_m_C": 10,
    "Ton_mm_C": 11,
    "Ton_m_C": 12,
    "kN_cm_C": 13,
    "kgf_cm_C": 14,
    "N_cm_C": 15,
    "Ton_cm_C": 16,
}

#: Sistemas ofrecidos en la interfaz, en el orden en que se muestran.
UNIT_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("Ton_m_C", "Ton · m (MKS)"),
    ("kgf_cm_C", "kgf · cm"),
    ("kgf_m_C", "kgf · m"),
    ("kN_m_C", "kN · m (SI)"),
    ("kN_mm_C", "kN · mm"),
    ("N_mm_C", "N · mm"),
    ("kip_ft_F", "kip · ft"),
    ("kip_in_F", "kip · in"),
)

#: Longitud de cada sistema, en metros (para convertir dimensiones a cm).
_LENGTH_IN_M: Dict[str, float] = {
    "in": 0.0254,
    "ft": 0.3048,
    "mm": 0.001,
    "cm": 0.01,
    "m": 1.0,
}


@dataclass(frozen=True)
class UnitSystem:
    """Sistema de unidades de un conjunto de datos."""

    key: str = "Ton_m_C"
    force: str = "tonf"
    length: str = "m"
    temperature: str = "C"

    @property
    def moment(self) -> str:
        return f"{self.force}-{self.length}"

    @property
    def label(self) -> str:
        return f"{self.force}, {self.length}, {self.temperature}"

    @property
    def etabs_code(self) -> Optional[int]:
        return E_UNITS.get(self.key)

    @property
    def length_to_cm(self) -> float:
        """Factor para pasar una longitud de este sistema a centímetros."""
        return _LENGTH_IN_M.get(self.length, 1.0) * 100.0


_FORCE_BY_KEY = {
    "lb": "lb", "kip": "kip", "kN": "kN", "kgf": "kgf", "N": "N", "Ton": "tonf",
}


def unit_system(key: str) -> UnitSystem:
    """Construye un :class:`UnitSystem` desde una clave de ``E_UNITS``."""
    if key not in E_UNITS:
        raise ValueError(f"Sistema de unidades desconocido: {key!r}")
    force, length, temp = key.split("_")
    return UnitSystem(key=key, force=_FORCE_BY_KEY.get(force, force),
                      length=length, temperature=temp)


def parse_units_label(label: Optional[str]) -> UnitSystem:
    """Interpreta la etiqueta de unidades que trae un .e2k (``"TON" "M" "C"``).

    Si no se reconoce, devuelve el sistema MKS con la etiqueta original
    conservada en ``force``/``length`` para no perder la información del
    archivo.
    """
    if not label:
        return UnitSystem()
    parts = [p.strip() for p in str(label).replace(",", " ").split() if p.strip()]
    if not parts:
        return UnitSystem()
    force_raw = parts[0]
    length_raw = parts[1].lower() if len(parts) > 1 else "m"
    temp_raw = parts[2].upper() if len(parts) > 2 else "C"
    force_map = {
        "ton": "Ton", "tonf": "Ton", "kn": "kN", "kgf": "kgf", "kg": "kgf",
        "n": "N", "lb": "lb", "kip": "kip",
    }
    force_key = force_map.get(force_raw.lower())
    length_key = length_raw if length_raw in _LENGTH_IN_M else None
    if force_key and length_key:
        key = f"{force_key}_{length_key}_{'F' if force_key in ('lb', 'kip') else 'C'}"
        if key in E_UNITS:
            return unit_system(key)
    return UnitSystem(key="", force=force_raw.lower(), length=length_raw,
                      temperature=temp_raw)


def length_to_cm(value: Optional[float], units: UnitSystem) -> Optional[float]:
    """Convierte una longitud del sistema dado a centímetros."""
    if value is None:
        return None
    return value * units.length_to_cm
