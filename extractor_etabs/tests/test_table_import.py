"""Pruebas del importador de tablas exportadas de ETABS."""

from __future__ import annotations

import os
import tempfile
import unittest

from extractor_etabs.core.table_import import parse_table_cells, parse_table_file

EJEMPLO = os.path.join(os.path.dirname(__file__), "..", "ejemplos",
                       "element_forces_beams.csv")

DESPLAZAMIENTOS = """TABLE:  "Joint Displacements"
Story,Label,Unique Name,Output Case,Case Type,Ux,Uy,Uz,Rx,Ry,Rz
,,,,,m,m,m,rad,rad,rad
Azotea,5,101,Sx,LinStatic,0.031200,0.000100,-0.000900,0.000010,0.000200,0.000001
Azotea,6,102,Sx,LinStatic,0.031100,0.000100,-0.001200,0.000010,0.000200,0.000001
Nivel 1,7,103,CM+CV,Combination,0.000200,0.000000,-0.002100,0.000000,0.000100,0.000000
"""

DERIVAS = """TABLE:  "Story Drifts"
Story,Output Case,Case Type,Step Type,Direction,Drift,Label,X,Y,Z
,,,,,,,m,m,m
Azotea,Sx,LinStatic,Max,X,0.004200,12,21,13,14.8
Nivel 1,Sx,LinStatic,Max,X,0.006100,4,21,0,4
"""

REACCIONES = """TABLE:  "Base Reactions"
Output Case,Case Type,Step Type,FX,FY,FZ,MX,MY,MZ
,,,tonf,tonf,tonf,tonf-m,tonf-m,tonf-m
CM,LinStatic,,0,0,-1250.4,8100.2,-13000.5,0
Sx,LinStatic,,180.5,0,0,0,-2100.3,1900.1
"""

TABULADO = ("Story\tBeam\tUnique Name\tOutput Case\tStation\tV2\tM3\n"
            "\t\t\t\tm\ttonf\ttonf-m\n"
            "Azotea\tB1\t101\tCM\t0.0000\t5.0\t-3.0\n"
            "Azotea\tB1\t101\tCM\t1.0000\t2.5\t0.75\n"
            "Azotea\tB1\t101\tCM\t2.0000\t0.0\t2.0\n")


def _cells(text: str, delimiter: str = ",") -> list:
    return [line.split(delimiter) for line in text.splitlines()]


class TestFuerzasDelEjemplo(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = parse_table_file(EJEMPLO)

    def test_lee_todos_los_renglones(self) -> None:
        self.assertTrue(self.result.ok)
        self.assertEqual(len(self.result.frame_forces), 4284)
        self.assertEqual(self.result.source, "tabla")

    def test_detecta_unidades_del_renglon_de_unidades(self) -> None:
        self.assertEqual(self.result.units.length, "m")
        self.assertEqual(self.result.units.force, "tonf")
        self.assertEqual(self.result.units.moment, "tonf-m")

    def test_casos_y_niveles(self) -> None:
        self.assertIn("1.3CM+1.5CV", self.result.cases)
        self.assertEqual(len(self.result.cases), 7)
        self.assertEqual(self.result.stories,
                         ["Azotea", "Nivel 1", "Nivel 2", "Nivel 3"])

    def test_serie_ordenada_por_estacion(self) -> None:
        serie = self.result.series("Azotea", "B1", "1.3CM+1.5CV")
        self.assertEqual(len(serie), 9)
        self.assertAlmostEqual(serie[0].station, 0.0)
        self.assertAlmostEqual(serie[-1].station, 7.0)
        self.assertAlmostEqual(serie[0].M3, -9.2050)
        self.assertAlmostEqual(serie[0].V2, 11.2841)
        self.assertEqual([s.station for s in serie],
                         sorted(s.station for s in serie))

    def test_envolvente(self) -> None:
        envelope = self.result.envelope("Azotea", "B1")
        self.assertAlmostEqual(envelope["M3_max"], 9.0572)
        self.assertAlmostEqual(envelope["M3_min"], -17.2934)
        self.assertAlmostEqual(envelope["V2_max"], 11.2841)

    def test_reporta_que_faltan_deformaciones(self) -> None:
        self.assertTrue(any("Deformaciones" in m for m in self.result.missing))


class TestOtrasTablas(unittest.TestCase):
    def test_desplazamientos_con_ux_uy_uz(self) -> None:
        result = parse_table_cells(_cells(DESPLAZAMIENTOS), "d.csv")
        self.assertEqual(len(result.displacements), 3)
        first = result.displacements[0]
        self.assertEqual(first.point, "101")
        self.assertEqual(first.case, "Sx")
        self.assertAlmostEqual(first.U1, 0.0312)
        self.assertAlmostEqual(first.U3, -0.0009)
        self.assertAlmostEqual(first.R2, 0.0002)
        self.assertEqual(first.story, "Azotea")
        self.assertIn("Sx", result.cases)

    def test_derivas(self) -> None:
        result = parse_table_cells(_cells(DERIVAS), "dr.csv")
        self.assertEqual(len(result.drifts), 2)
        self.assertAlmostEqual(result.drifts[1].drift, 0.0061)
        self.assertEqual(result.drifts[0].direction, "X")
        self.assertEqual(result.drifts[0].step_type, "Max")

    def test_reacciones(self) -> None:
        result = parse_table_cells(_cells(REACCIONES), "r.csv")
        self.assertEqual(len(result.reactions), 2)
        self.assertAlmostEqual(result.reactions[0].FZ, -1250.4)
        self.assertAlmostEqual(result.reactions[1].FX, 180.5)

    def test_archivo_con_varias_tablas(self) -> None:
        combined = DESPLAZAMIENTOS + "\n" + DERIVAS + "\n" + REACCIONES
        result = parse_table_cells(_cells(combined), "todo.csv")
        self.assertEqual(len(result.displacements), 3)
        self.assertEqual(len(result.drifts), 2)
        self.assertEqual(len(result.reactions), 2)
        self.assertTrue(any("Tablas leídas" in w for w in result.warnings))

    def test_separador_de_tabulador(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "fuerzas.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(TABULADO)
            result = parse_table_file(path)
        self.assertEqual(len(result.frame_forces), 3)
        self.assertAlmostEqual(result.frame_forces[2].M3, 2.0)
        self.assertAlmostEqual(result.frame_forces[0].V2, 5.0)
        # La tabla no trae P: la columna queda vacía, no en cero.
        self.assertIsNone(result.frame_forces[0].P)

    def test_tabla_desconocida(self) -> None:
        result = parse_table_cells(_cells("a,b,c\n1,2,3\n"), "x.csv")
        self.assertIsNotNone(result.error)
        self.assertIn("No se reconoció", result.error)

    def test_renglones_incompletos_se_cuentan(self) -> None:
        texto = ("Story,Beam,Output Case,Station,M3\n"
                 ",,,m,tonf-m\n"
                 "Azotea,B1,CM,0.0,1.0\n"
                 "Azotea,,CM,1.0,2.0\n"
                 "Azotea,B1,CM,2.0,3.0\n")
        result = parse_table_cells(_cells(texto), "x.csv")
        self.assertEqual(len(result.frame_forces), 2)
        self.assertTrue(any("incompletos" in w for w in result.warnings))
        self.assertTrue(any("V2" in m for m in result.missing))

    def test_merge_acumula(self) -> None:
        fuerzas = parse_table_file(EJEMPLO)
        derivas = parse_table_cells(_cells(DERIVAS), "dr.csv")
        antes = len(fuerzas.frame_forces)
        fuerzas.merge(derivas)
        self.assertEqual(len(fuerzas.frame_forces), antes)
        self.assertEqual(len(fuerzas.drifts), 2)


if __name__ == "__main__":
    unittest.main()
