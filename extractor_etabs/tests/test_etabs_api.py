"""Pruebas de la ruta OAPI contra el ETABS simulado de ``fake_etabs``.

Cubren lo que suele romperse al hablar con la API de CSI: el orden de los
parámetros por referencia (distinto en comtypes y en pythonnet), la selección de
casos para salida, el camino alterno cuando el grupo «All» no funciona y el
reporte honesto cuando el modelo no tiene el análisis corrido.
"""

from __future__ import annotations

import unittest

from extractor_etabs.core.etabs_api import (
    DBL, DBL_ARR, INT, STR, STR_ARR, EtabsError, unavailable_reason,
)
from extractor_etabs.core.extractors import (
    ExtractionOptions, ModelReader, ResultsReader,
)

from fake_etabs import make_connection


class TestDesempacado(unittest.TestCase):
    def test_orden_de_comtypes(self) -> None:
        connection, sap = make_connection(ret_first=False)
        outs = connection.call(sap.GetProgramInfo, (), (STR, STR, STR))
        self.assertEqual(outs, ["ETABS", "22.2.0", "Ultimate"])

    def test_orden_de_pythonnet(self) -> None:
        connection, sap = make_connection(ret_first=True)
        outs = connection.call(sap.GetProgramInfo, (), (STR, STR, STR))
        self.assertEqual(outs, ["ETABS", "22.2.0", "Ultimate"])

    def test_codigo_de_error_se_convierte_en_excepcion(self) -> None:
        connection, sap = make_connection()
        with self.assertRaises(EtabsError) as ctx:
            connection.call(sap.FrameObj.GetLabelFromName, ("inexistente",),
                            (STR, STR), what="etiqueta")
        self.assertIn("código 1", str(ctx.exception))

    def test_try_call_anota_y_sigue(self) -> None:
        connection, sap = make_connection()
        self.assertIsNone(connection.try_call(
            sap.FrameObj.GetLabelFromName, ("inexistente",), (STR, STR),
            what="etiqueta"))
        self.assertTrue(connection.warnings)

    def test_metodo_sin_salidas(self) -> None:
        connection, sap = make_connection()
        self.assertEqual(connection.call(sap.SetPresentUnits, (14,), ()), [])
        self.assertEqual(sap.units, 14)

    def test_tabla_generica(self) -> None:
        connection, _ = make_connection()
        fields, rows = connection.table("Story Drifts")
        self.assertEqual(fields, ["Story", "Drift"])
        self.assertEqual(rows, [["Azotea", "0.0032"], ["Nivel 1", "0.0041"]])


class TestLecturaDelModelo(unittest.TestCase):
    def test_geometria_completa(self) -> None:
        connection, _ = make_connection()
        model = ModelReader(connection).read("Ton_m_C")

        self.assertEqual(model.info.program, "ETABS")
        self.assertEqual(model.info.source, "oapi")
        self.assertEqual(model.info.file, r"C:\modelos\torre.EDB")
        self.assertEqual([s.name for s in model.stories], ["Azotea", "Nivel 1"])
        self.assertAlmostEqual(model.stories[0].elevation, 7.0)
        self.assertEqual([g.label for g in model.grids_x], ["A", "B", "C"])
        self.assertEqual(model.load_cases, ["CM", "CV"])
        self.assertEqual(model.load_combos, ["1.3CM+1.5CV", "CM+CV"])
        self.assertEqual(len(model.frames), 4)
        self.assertEqual(len(model.beams()), 3)

    def test_secciones_en_centimetros(self) -> None:
        connection, _ = make_connection()
        model = ModelReader(connection).read("Ton_m_C")
        section = model.sections["V-30X60"]
        self.assertAlmostEqual(section.b_cm, 30.0)      # 0.30 m → 30 cm
        self.assertAlmostEqual(section.h_cm, 60.0)
        self.assertEqual(section.dim_source, "api")

    def test_una_trabe_con_sus_ejes(self) -> None:
        connection, _ = make_connection()
        model = ModelReader(connection).read("Ton_m_C")
        beam = model.frame("1")
        self.assertEqual(beam.label, "B1")
        self.assertEqual(beam.story, "Azotea")
        self.assertEqual(beam.kind, "BEAM")
        self.assertEqual(beam.direction, "X")
        self.assertEqual((beam.grid_i, beam.grid_j), ("A", "B"))
        self.assertEqual(beam.grid_line, "1")
        self.assertAlmostEqual(beam.length, 6.0)
        self.assertEqual(model.frame("4").kind, "COLUMN")
        self.assertEqual(model.frame("4").direction, "Z")

    def test_filtro_por_tipo(self) -> None:
        connection, _ = make_connection()
        model = ModelReader(connection).read("Ton_m_C", kinds=["BEAM"])
        self.assertEqual(len(model.frames), 3)
        self.assertTrue(all(f.kind == "BEAM" for f in model.frames))

    def test_sin_ejes_avisa_pero_no_falla(self) -> None:
        connection, _ = make_connection(no_grids=True)
        model = ModelReader(connection).read("Ton_m_C")
        self.assertEqual(model.grids_x, [])
        self.assertTrue(any("ejes" in m.lower() for m in model.missing))
        self.assertTrue(model.frames)

    def test_modelo_sin_analisis_lo_reporta(self) -> None:
        connection, _ = make_connection(locked=False)
        model = ModelReader(connection).read("Ton_m_C")
        self.assertTrue(any("no está bloqueado" in m for m in model.missing))

    def test_progreso_puede_cancelar(self) -> None:
        from extractor_etabs.core.extractors import Cancelled

        connection, _ = make_connection()
        llamadas = []

        def progreso(mensaje: str, done: int, total: int) -> bool:
            llamadas.append(mensaje)
            return len(llamadas) < 2          # cancela en el segundo aviso

        with self.assertRaises(Cancelled):
            ModelReader(connection).read("Ton_m_C", progress=progreso)


class TestExtraccionDeResultados(unittest.TestCase):
    def _extraer(self, **kwargs) -> tuple:
        connection, sap = make_connection(**kwargs)
        model = ModelReader(connection).read("Ton_m_C")
        options = ExtractionOptions(
            combos=["1.3CM+1.5CV"], cases=["CM"], deflections=True,
            reactions=True, kinds=["BEAM", "COLUMN"])
        result = ResultsReader(connection).extract(model, options)
        return result, model, sap

    def test_extraccion_completa(self) -> None:
        result, model, sap = self._extraer()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.source, "oapi")
        self.assertEqual(sorted(result.cases), ["1.3CM+1.5CV", "CM"])
        self.assertEqual(sap.selected, ["CM", "1.3CM+1.5CV"])
        # 4 barras × 2 casos × 5 estaciones
        self.assertEqual(len(result.frame_forces), 40)
        self.assertTrue(result.displacements)
        self.assertTrue(result.drifts)
        self.assertEqual(len(result.reactions), 2)

    def test_los_renglones_traen_nivel_y_etiqueta(self) -> None:
        result, _, _ = self._extraer()
        row = next(r for r in result.frame_forces if r.frame == "1")
        self.assertEqual(row.story, "Azotea")
        self.assertEqual(row.label, "B1")
        self.assertIn(row.case, ("CM", "1.3CM+1.5CV"))

    def test_series_y_envolvente(self) -> None:
        result, _, _ = self._extraer()
        serie = result.series("Azotea", "1", "1.3CM+1.5CV")
        self.assertEqual([s.station for s in serie], [0.0, 1.5, 3.0, 4.5, 6.0])
        self.assertAlmostEqual(serie[2].M3, 7.5)
        envelope = result.envelope("Azotea", "1")
        self.assertAlmostEqual(envelope["M3_max"], 7.5)
        self.assertAlmostEqual(envelope["M3_min"], -9.0)

    def test_deflexiones_solo_de_trabes(self) -> None:
        result, _, _ = self._extraer()
        self.assertTrue(result.deflections)
        barras = {d.frame for d in result.deflections}
        self.assertNotIn("4", barras)         # la columna no se deflexiona aquí
        peor = max(result.deflections, key=lambda d: abs(d.deflection or 0.0))
        self.assertGreater(abs(peor.deflection), 0.0)
        self.assertTrue(any("doble integración" in w for w in result.warnings))

    def test_los_desplazamientos_de_nudo_entran_como_frontera(self) -> None:
        """U3 del nudo desplaza la curva: se comprueba que sí se usa."""
        result, model, _ = self._extraer()
        deflexiones = [d for d in result.deflections if d.frame == "1"]
        extremos = [d for d in deflexiones if d.station in (0.0, 6.0)]
        # U3 = -0.004 en ETABS → 0.004 hacia abajo en los dos extremos.
        for row in extremos:
            self.assertAlmostEqual(row.deflection, 0.004, places=6)

    def test_si_el_grupo_falla_pide_barra_por_barra(self) -> None:
        result, _, _ = self._extraer(fail_group=True)
        self.assertEqual(len(result.frame_forces), 40)
        self.assertTrue(result.ok)

    def test_sin_analisis_no_extrae(self) -> None:
        connection, sap = make_connection(locked=False)
        model = ModelReader(connection).read("Ton_m_C")
        options = ExtractionOptions(combos=["CM+CV"])
        result = ResultsReader(connection).extract(model, options)
        self.assertFalse(result.ok)
        self.assertIn("análisis corrido", result.error)
        self.assertEqual(sap.analysis_runs, 0)

    def test_puede_correr_el_analisis(self) -> None:
        connection, sap = make_connection(locked=False)
        model = ModelReader(connection).read("Ton_m_C")
        options = ExtractionOptions(combos=["CM+CV"],
                                    run_analysis_if_unlocked=True)
        result = ResultsReader(connection).extract(model, options)
        self.assertEqual(sap.analysis_runs, 1)
        self.assertTrue(result.ok, result.error)

    def test_sin_casos_no_hace_nada(self) -> None:
        connection, _ = make_connection()
        model = ModelReader(connection).read("Ton_m_C")
        result = ResultsReader(connection).extract(model, ExtractionOptions())
        self.assertIn("ningún caso", result.error)

    def test_caso_inexistente_se_rechaza(self) -> None:
        connection, _ = make_connection()
        model = ModelReader(connection).read("Ton_m_C")
        options = ExtractionOptions(combos=["NO_EXISTE"])
        result = ResultsReader(connection).extract(model, options)
        self.assertIn("no aceptó", result.error)

    def test_filtro_por_nivel(self) -> None:
        connection, _ = make_connection()
        model = ModelReader(connection).read("Ton_m_C")
        options = ExtractionOptions(combos=["CM+CV"], stories=["Nivel 1"],
                                    kinds=["BEAM"], displacements=False,
                                    drifts=False)
        result = ResultsReader(connection).extract(model, options)
        self.assertEqual({r.story for r in result.frame_forces}, {"Nivel 1"})


class TestDisponibilidad(unittest.TestCase):
    def test_explica_por_que_no_hay_oapi(self) -> None:
        import sys

        reason = unavailable_reason()
        if sys.platform.startswith("win"):
            self.assertTrue(reason is None or "enlace" in reason)
        else:
            self.assertIsNotNone(reason)
            self.assertIn("Windows", reason)


if __name__ == "__main__":
    unittest.main()
