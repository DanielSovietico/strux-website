"""Pruebas del lector de .e2k."""

from __future__ import annotations

import os
import unittest

from extractor_etabs.core.e2k_parser import (
    parse_e2k, parse_e2k_file, section_dims_from_name,
)

EJEMPLO = os.path.join(os.path.dirname(__file__), "..", "ejemplos",
                       "modelo_ejemplo.e2k")

E2K_EN_CENTIMETROS = """$ PROGRAM INFORMATION
  PROGRAM  "ETABS"  VERSION "21.0.0"

$ CONTROLS
  UNITS  "KGF"  "CM"  "C"
  TITLE1  "Modelo en centímetros"

$ STORIES - IN SEQUENTIAL ORDER FROM TOP
  STORY  "N1"  HEIGHT 300
  STORY  "Base"  ELEV 0

$ GRIDS
  GRID  "GLOBAL"  LABEL "A"  DIR "X"  COORD 0
  GRID  "GLOBAL"  LABEL "B"  DIR "X"  COORD 500
  GRID  "GLOBAL"  LABEL "1"  DIR "Y"  COORD 0

$ FRAME SECTIONS
  FRAMESECTION  "V1"  MATERIAL "C250"  SHAPE "Concrete Rectangular"  D 60  B 25
  FRAMESECTION  "RARA"  MATERIAL "C250"  SHAPE "Concrete Circular"

$ POINT COORDINATES
  POINT  "1"  0  0
  POINT  "2"  500  0

$ LINE CONNECTIVITIES
  LINE  "V-1"  BEAM  "1"  "2"  0

$ LINE ASSIGNS
  LINEASSIGN  "V-1"  "N1"  SECTION "V1"

$ LOAD PATTERNS
  LOADPATTERN  "CM"  TYPE  "Dead"  SELFWEIGHT  0

$ LOAD COMBINATIONS
  COMBO  "1.4CM"  TYPE "Linear Add"
  COMBO  "1.4CM"  LOAD "CM"  SF 1.4

$ END OF MODEL FILE
"""


class TestEjemploCompleto(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = parse_e2k_file(EJEMPLO)

    def test_lee_encabezado_y_unidades(self) -> None:
        self.assertEqual(self.model.info.program, "ETABS")
        self.assertEqual(self.model.info.version, "22.2.0")
        self.assertEqual(self.model.info.title,
                         "Edificio Ejemplo - Marco de concreto")
        self.assertEqual(self.model.info.units.length, "m")
        self.assertEqual(self.model.info.units.force, "tonf")
        self.assertEqual(self.model.info.source, "e2k")

    def test_resuelve_cotas_desde_alturas(self) -> None:
        elevations = {s.name: s.elevation for s in self.model.stories}
        self.assertEqual(elevations["Base"], 0.0)
        self.assertAlmostEqual(elevations["Nivel 1"], 4.0)
        self.assertAlmostEqual(elevations["Nivel 2"], 7.6)
        self.assertAlmostEqual(elevations["Nivel 3"], 11.2)
        self.assertAlmostEqual(elevations["Azotea"], 14.8)
        self.assertTrue(self.model.stories[-1].is_base)

    def test_conteos(self) -> None:
        counts = self.model.counts()
        self.assertEqual(counts["trabes"], 68)
        self.assertEqual(counts["columnas"], 48)
        self.assertEqual(counts["ejes"], 7)
        self.assertEqual(counts["secciones"], 3)
        self.assertEqual(counts["combinaciones"], 7)
        self.assertEqual(self.model.load_patterns,
                         ["CM", "CV", "CVa", "Sx", "Sy"])

    def test_secciones_en_centimetros(self) -> None:
        section = self.model.sections["V-30X70"]
        self.assertAlmostEqual(section.b_cm, 30.0)
        self.assertAlmostEqual(section.h_cm, 70.0)
        self.assertEqual(section.dim_source, "e2k")
        self.assertAlmostEqual(section.inertia_cm4, 30.0 * 70.0 ** 3 / 12.0)
        self.assertAlmostEqual(section.area_cm2, 2100.0)

    def test_geometria_de_una_trabe(self) -> None:
        beam = next(f for f in self.model.frames
                    if f.name == "B1" and f.story == "Azotea")
        self.assertEqual(beam.kind, "BEAM")
        self.assertEqual(beam.direction, "X")
        self.assertEqual(beam.section, "V-30X70")
        self.assertAlmostEqual(beam.length, 7.0)
        self.assertEqual(beam.grid_line, "1")      # corre sobre el eje Y = 0
        self.assertEqual((beam.grid_i, beam.grid_j), ("A", "B"))
        self.assertAlmostEqual(beam.zi, 14.8)

    def test_columnas_bajan_un_nivel(self) -> None:
        column = next(f for f in self.model.frames
                      if f.name == "C1" and f.story == "Azotea")
        self.assertEqual(column.kind, "COLUMN")
        self.assertEqual(column.direction, "Z")
        self.assertAlmostEqual(column.zi, 14.8)
        self.assertAlmostEqual(column.zj, 11.2)
        self.assertAlmostEqual(column.length, 3.6, places=6)

    def test_reporta_que_no_trae_resultados(self) -> None:
        self.assertTrue(any("Elementos mecánicos" in m
                            for m in self.model.missing))
        self.assertIsNone(self.model.error)
        self.assertTrue(self.model.ok)


class TestUnidadesYCasosLimite(unittest.TestCase):
    def test_dimensiones_con_unidades_en_centimetros(self) -> None:
        model = parse_e2k(E2K_EN_CENTIMETROS, "cm.e2k")
        self.assertEqual(model.info.units.length, "cm")
        section = model.sections["V1"]
        self.assertAlmostEqual(section.b_cm, 25.0)
        self.assertAlmostEqual(section.h_cm, 60.0)
        beam = model.frames[0]
        self.assertAlmostEqual(beam.length, 500.0)      # sigue en cm
        self.assertAlmostEqual(model.stories[0].elevation, 300.0)

    def test_seccion_sin_dimensiones_avisa(self) -> None:
        model = parse_e2k(E2K_EN_CENTIMETROS, "cm.e2k")
        self.assertIsNone(model.sections["RARA"].b_cm)
        self.assertTrue(any("RARA" in w for w in model.warnings))

    def test_combos_repetidos_no_se_duplican(self) -> None:
        model = parse_e2k(E2K_EN_CENTIMETROS, "cm.e2k")
        self.assertEqual(model.load_combos, ["1.4CM"])

    def test_archivo_que_no_es_e2k(self) -> None:
        model = parse_e2k("Hola, soy un archivo cualquiera.", "x.txt")
        self.assertIsNotNone(model.error)
        self.assertIn("no tiene la estructura", model.error)
        self.assertFalse(model.ok)

    def test_sin_asignaciones_reporta_error(self) -> None:
        text = E2K_EN_CENTIMETROS.replace(
            '  LINEASSIGN  "V-1"  "N1"  SECTION "V1"', "")
        model = parse_e2k(text, "x.e2k")
        self.assertIsNotNone(model.error)
        self.assertIn("no contiene barras", model.error)

    def test_punto_inexistente_se_avisa(self) -> None:
        text = E2K_EN_CENTIMETROS.replace('  POINT  "2"  500  0', "")
        model = parse_e2k(text, "x.e2k")
        self.assertTrue(any("punto inexistente" in w for w in model.warnings))

    def test_dimensiones_desde_el_nombre(self) -> None:
        self.assertEqual(section_dims_from_name("V-30X70"), (30.0, 70.0))
        self.assertEqual(section_dims_from_name("25x60"), (25.0, 60.0))
        self.assertIsNone(section_dims_from_name("Circular"))
        self.assertIsNone(section_dims_from_name(""))


if __name__ == "__main__":
    unittest.main()
