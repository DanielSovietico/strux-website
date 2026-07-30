"""Deflexión de trabes por doble integración de la curvatura M3/EI.

ETABS no expone una tabla de deflexión a lo largo de la barra: entrega los
desplazamientos de los **nudos**. Lo que sí entrega en cada estación es M3, y de
ahí se obtiene la curva de deflexión integrando dos veces la curvatura
``κ = M3 / (E·I)``, con los desplazamientos de los nudos extremos como
condiciones de frontera cuando están disponibles.

Es un cálculo, no una lectura, y así se etiqueta en la interfaz y en los
reportes. Sus supuestos son explícitos:

* viga de Euler-Bernoulli, ``E·I`` constante en el claro;
* la curvatura se toma solo de M3 (flexión en el plano vertical);
* sin condiciones de frontera se supone ``v = 0`` en los extremos, es decir, la
  deflexión resulta relativa a la recta que une los nudos;
* la inercia es la bruta de la sección rectangular, multiplicable por un factor
  (``inertia_factor``) para representar una inercia efectiva agrietada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .model import Section
from .units import UnitSystem

#: Cuántos kgf hay en una unidad de fuerza de cada sistema.
_KGF_PER_FORCE = {
    "kgf": 1.0, "tonf": 1000.0, "kN": 101.9716213, "N": 0.1019716213,
    "lb": 0.45359237, "kip": 453.59237,
}


@dataclass
class DeflectionCurve:
    """Resultado del cálculo para un claro."""

    stations: List[float]
    values: List[float]              # deflexión hacia abajo, positiva
    max_value: float = 0.0
    max_station: float = 0.0
    span: float = 0.0
    note: Optional[str] = None

    @property
    def span_ratio(self) -> Optional[float]:
        """Relación ``L/δ`` (entero) para comparar contra límites normativos."""
        if not self.max_value or self.max_value <= 0 or not self.span:
            return None
        return self.span / self.max_value


def young_modulus_in(units: UnitSystem, value: float,
                     value_units: str = "kgf/cm2") -> float:
    """Convierte E al sistema de unidades de los resultados.

    ``value_units`` acepta ``kgf/cm2``, ``tonf/cm2``, ``MPa``, ``kN/cm2``,
    ``kip/in2`` y ``psi``.
    """
    to_kgf_cm2 = {
        "kgf/cm2": 1.0,
        "tonf/cm2": 1000.0,
        "mpa": 10.1971621,            # 1 MPa = 10.197 kgf/cm²
        "kn/cm2": 101.9716213,
        "kip/in2": 70.3069579,        # 1 ksi = 70.307 kgf/cm²
        "psi": 0.0703069579,
    }
    factor = to_kgf_cm2.get(value_units.strip().lower())
    if factor is None:
        raise ValueError(f"Unidad de E no reconocida: {value_units!r}")
    e_kgf_cm2 = float(value) * factor
    kgf_per_force = _KGF_PER_FORCE.get(units.force, 1000.0)
    cm_per_length = units.length_to_cm
    return e_kgf_cm2 / kgf_per_force * cm_per_length ** 2


def inertia_in(units: UnitSystem, inertia_cm4: float) -> float:
    """Pasa una inercia en cm⁴ a la longitud del sistema, a la cuarta."""
    return float(inertia_cm4) / units.length_to_cm ** 4


def section_ei(section: Optional[Section], units: UnitSystem,
               e_value: float, e_units: str = "kgf/cm2",
               inertia_factor: float = 1.0) -> Optional[float]:
    """``E·I`` en las unidades de los resultados, o ``None`` si falta la sección."""
    if section is None or section.inertia_cm4 is None:
        return None
    e = young_modulus_in(units, e_value, e_units)
    i = inertia_in(units, section.inertia_cm4 * max(inertia_factor, 1e-9))
    if e <= 0 or i <= 0:
        return None
    return e * i


def deflection_from_moments(stations: Sequence[float], moments: Sequence[float],
                            ei: float, delta_i: float = 0.0,
                            delta_j: float = 0.0) -> DeflectionCurve:
    """Integra ``M/EI`` dos veces sobre las estaciones dadas.

    ``delta_i`` y ``delta_j`` son los desplazamientos verticales de los nudos
    extremos (positivos hacia abajo). El signo del resultado sigue la convención
    de la ingeniería práctica: **positivo hacia abajo**.
    """
    pairs = sorted(
        ((float(x), float(m)) for x, m in zip(stations, moments) if m is not None),
        key=lambda p: p[0])
    # Una estación puede repetirse (mismo punto, varios pasos): se conserva la
    # de mayor magnitud para no aplanar el diagrama.
    unique: List[Tuple[float, float]] = []
    for x, m in pairs:
        if unique and abs(x - unique[-1][0]) < 1e-9:
            if abs(m) > abs(unique[-1][1]):
                unique[-1] = (x, m)
            continue
        unique.append((x, m))

    if len(unique) < 3:
        return DeflectionCurve([], [], note=(
            "Se necesitan al menos tres estaciones con M3 para integrar la "
            "curvatura; ETABS entregó menos."))
    if not ei or ei <= 0:
        return DeflectionCurve([], [], note=(
            "Falta E·I: la sección no trae dimensiones legibles o no se indicó "
            "el módulo de elasticidad."))

    xs = [p[0] for p in unique]
    curvature = [p[1] / ei for p in unique]
    span = xs[-1] - xs[0]
    if span <= 0:
        return DeflectionCurve([], [], note="El claro de la barra resultó nulo.")

    # θ(x) = ∫κ dx   y   v(x) = ∫θ dx   (regla del trapecio acumulada)
    theta = [0.0]
    for k in range(1, len(xs)):
        dx = xs[k] - xs[k - 1]
        theta.append(theta[-1] + 0.5 * (curvature[k] + curvature[k - 1]) * dx)
    v = [0.0]
    for k in range(1, len(xs)):
        dx = xs[k] - xs[k - 1]
        v.append(v[-1] + 0.5 * (theta[k] + theta[k - 1]) * dx)

    # v se define hacia arriba: se ajusta la recta para cumplir los extremos.
    v_i, v_j = -float(delta_i), -float(delta_j)
    slope = (v_j - (v[-1] + v_i - v[0])) / span
    adjusted = [v[k] + v_i - v[0] + slope * (xs[k] - xs[0]) for k in range(len(xs))]

    values = [-a for a in adjusted]          # positivo hacia abajo
    peak = max(range(len(values)), key=lambda k: abs(values[k]))
    return DeflectionCurve(stations=xs, values=values, span=span,
                           max_value=values[peak], max_station=xs[peak])


def deflection_limit(span: float, ratio: float = 240.0,
                     extra: float = 0.0) -> float:
    """Límite de flecha ``L/ratio + extra`` (NTC-Concreto 2023 §13.4 usa 240)."""
    return span / max(ratio, 1e-9) + extra
