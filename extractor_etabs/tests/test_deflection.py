"""La deflexión calculada se contrasta contra la solución analítica.

Es la única cantidad que la aplicación *calcula* en vez de leer, así que conviene
tenerla amarrada a un caso con respuesta cerrada: viga libremente apoyada con
carga uniforme, donde ``δ_máx = 5wL⁴/(384EI)``.
"""

from __future__ import annotations

import unittest

from extractor_etabs.core.deflection import (
    deflection_from_moments, deflection_limit, inertia_in, section_ei,
    young_modulus_in,
)
from extractor_etabs.core.model import Section
from extractor_etabs.core.units import unit_system


class TestDeflectionIntegration(unittest.TestCase):
    def test_simply_supported_uniform_load(self) -> None:
        length, w, ei, stations = 7.0, 4.0, 20000.0, 41
        xs = [length * i / (stations - 1) for i in range(stations)]
        moments = [w * x * (length - x) / 2.0 for x in xs]

        curve = deflection_from_moments(xs, moments, ei)
        expected = 5.0 * w * length ** 4 / (384.0 * ei)

        self.assertAlmostEqual(curve.max_station, length / 2.0, places=6)
        self.assertAlmostEqual(curve.max_value, expected,
                               delta=expected * 0.005)
        self.assertGreater(curve.max_value, 0.0, "debe dar hacia abajo")
        self.assertAlmostEqual(curve.span, length, places=9)
        self.assertAlmostEqual(curve.values[0], 0.0, places=9)
        self.assertAlmostEqual(curve.values[-1], 0.0, places=9)
        self.assertAlmostEqual(curve.span_ratio, length / expected,
                               delta=length / expected * 0.005)

    def test_constant_moment(self) -> None:
        """Momento constante: la flecha respecto a la cuerda es ``M L²/(8EI)``."""
        length, moment, ei, stations = 6.0, 12.0, 15000.0, 25
        xs = [length * i / (stations - 1) for i in range(stations)]
        curve = deflection_from_moments(xs, [moment] * stations, ei)
        expected = moment * length ** 2 / (8.0 * ei)
        self.assertAlmostEqual(curve.max_value, expected,
                               delta=expected * 0.002)

    def test_hogging_moment_lifts_the_chord(self) -> None:
        """Con momento negativo la curva respecto a la cuerda va hacia arriba.

        Es el caso del apoyo de una trabe continua: la deflexión que interesa se
        mide desde la recta que une los nudos, así que un momento de signo
        contrario tiene que dar valores negativos (hacia arriba).
        """
        length, ei, stations = 5.0, 10000.0, 21
        xs = [length * i / (stations - 1) for i in range(stations)]
        curve = deflection_from_moments(xs, [-8.0] * stations, ei)
        self.assertLess(curve.max_value, 0.0)
        self.assertAlmostEqual(curve.max_value,
                               -8.0 * length ** 2 / (8.0 * ei),
                               delta=abs(8.0 * length ** 2 / (8.0 * ei)) * 0.002)

    def test_end_displacements_are_respected(self) -> None:
        xs = [0.0, 1.0, 2.0, 3.0, 4.0]
        moments = [0.0, 0.0, 0.0, 0.0, 0.0]
        curve = deflection_from_moments(xs, moments, 1000.0,
                                       delta_i=0.01, delta_j=0.03)
        self.assertAlmostEqual(curve.values[0], 0.01, places=9)
        self.assertAlmostEqual(curve.values[-1], 0.03, places=9)
        self.assertAlmostEqual(curve.values[2], 0.02, places=9)

    def test_reports_why_it_cannot_integrate(self) -> None:
        few = deflection_from_moments([0.0, 1.0], [0.0, 1.0], 1000.0)
        self.assertEqual(few.values, [])
        self.assertIn("tres estaciones", few.note or "")

        no_ei = deflection_from_moments([0.0, 1.0, 2.0], [0.0, 1.0, 0.0], 0.0)
        self.assertEqual(no_ei.values, [])
        self.assertIn("E·I", no_ei.note or "")

    def test_repeated_stations_keep_the_worst(self) -> None:
        """Una estación repetida (varios pasos) no debe aplanar el diagrama."""
        xs = [0.0, 1.0, 1.0, 2.0, 3.0]
        moments = [0.0, 2.0, 8.0, 2.0, 0.0]
        curve = deflection_from_moments(xs, moments, 1000.0)
        self.assertEqual(len(curve.stations), 4)


class TestUnitConversion(unittest.TestCase):
    def test_young_modulus_to_tonf_m2(self) -> None:
        units = unit_system("Ton_m_C")
        # 200 000 kgf/cm² = 2 000 000 tonf/m²
        self.assertAlmostEqual(young_modulus_in(units, 200000.0, "kgf/cm2"),
                               2.0e6, delta=1.0)

    def test_young_modulus_from_mpa(self) -> None:
        units = unit_system("kN_m_C")
        # 25 000 MPa = 25 000 000 kN/m²
        self.assertAlmostEqual(young_modulus_in(units, 25000.0, "MPa"),
                               2.5e7, delta=2000.0)

    def test_inertia_conversion(self) -> None:
        units = unit_system("Ton_m_C")
        self.assertAlmostEqual(inertia_in(units, 857500.0), 0.008575, places=9)

    def test_section_ei_uses_gross_inertia_times_factor(self) -> None:
        units = unit_system("Ton_m_C")
        section = Section(name="V-30X70", b_cm=30.0, h_cm=70.0)
        full = section_ei(section, units, 221359.0, "kgf/cm2", 1.0)
        half = section_ei(section, units, 221359.0, "kgf/cm2", 0.5)
        self.assertIsNotNone(full)
        self.assertAlmostEqual(half, full / 2.0, places=6)

    def test_section_without_dimensions_gives_none(self) -> None:
        units = unit_system("Ton_m_C")
        self.assertIsNone(section_ei(Section(name="X"), units, 1.0))
        self.assertIsNone(section_ei(None, units, 1.0))

    def test_unknown_e_units_raise(self) -> None:
        with self.assertRaises(ValueError):
            young_modulus_in(unit_system("Ton_m_C"), 1.0, "toneladas/legua")

    def test_limit_helper(self) -> None:
        self.assertAlmostEqual(deflection_limit(7.0, 240.0), 7.0 / 240.0,
                               places=9)
        self.assertAlmostEqual(deflection_limit(7.0, 480.0, 0.003),
                               7.0 / 480.0 + 0.003, places=9)


if __name__ == "__main__":
    unittest.main()
