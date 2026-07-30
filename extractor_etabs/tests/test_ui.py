"""Pruebas de la interfaz: se abre sin ETABS, muestra datos y filtra.

Corren sin pantalla física gracias al *backend* ``offscreen`` de Qt. Si PySide6
no está instalado, la prueba se marca como omitida en lugar de fallar: la capa
``core`` no depende de la interfaz.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    QT_DISPONIBLE = True
except ImportError:                     # pragma: no cover - entorno sin Qt
    QT_DISPONIBLE = False

BASE = os.path.join(os.path.dirname(__file__), "..", "ejemplos")
E2K = os.path.join(BASE, "modelo_ejemplo.e2k")
TABLA = os.path.join(BASE, "element_forces_beams.csv")


@unittest.skipUnless(QT_DISPONIBLE, "PySide6 no está instalado")
class TestVentanaPrincipal(unittest.TestCase):
    app = None
    window = None

    @classmethod
    def setUpClass(cls) -> None:
        from extractor_etabs.core.extractors import ExtractionOptions
        from extractor_etabs.ui.main_window import MainWindow

        cls.app = QApplication.instance() or QApplication(["test"])
        cls.window = MainWindow()
        cls.window.resize(1400, 900)
        # Se carga por la sesión directamente para no depender del hilo de
        # trabajo ni de los diálogos de archivo.
        session = cls.window.session
        session.load_e2k(E2K)
        session.load_table(TABLA)
        session.add_deflections(ExtractionOptions())
        cls.window._refresh_views()      # noqa: SLF001 (es una prueba)
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.window is not None:
            cls.window.worker.shutdown(1000)
            cls.window.close()

    def test_abre_con_las_cuatro_pestanas(self) -> None:
        titulos = [self.window.tabs.tabText(i)
                   for i in range(self.window.tabs.count())]
        self.assertEqual(titulos, ["Modelo", "Resultados", "Diagramas",
                                   "Registro"])

    def test_el_indicador_de_procedencia_dice_de_donde_viene_todo(self) -> None:
        texto = self.window.lbl_source.text()
        self.assertIn("modelo_ejemplo.e2k", texto)
        self.assertIn("element_forces_beams.csv", texto)

    def test_sin_oapi_los_botones_de_etabs_se_deshabilitan(self) -> None:
        import sys

        if sys.platform.startswith("win"):
            self.skipTest("en Windows la OAPI sí está disponible")
        self.assertFalse(self.window.panel.btn_connect.isEnabled())
        self.assertTrue(self.window.panel.btn_e2k.isEnabled())
        self.assertIn("Windows", self.window.panel.oapi_status.text())

    def test_la_tabla_trae_todos_los_renglones(self) -> None:
        page = self.window.results_view.pages["frame_forces"]
        self.assertEqual(page.model.rowCount(), 4284)
        self.assertEqual(page.visible_row_count(), 4284)
        self.assertIn("M3 (tonf-m)", page.model.columns)

    def test_los_filtros_reducen_los_renglones(self) -> None:
        page = self.window.results_view.pages["frame_forces"]
        combo = page._combos[0][1]        # noqa: SLF001 (filtro de nivel)
        combo.setCurrentIndex(combo.findText("Azotea"))
        self.app.processEvents()
        self.assertEqual(page.visible_row_count(), 1071)

        page.txt_search.setText("1.3CM+1.5CV")
        self.app.processEvents()
        self.assertLess(page.visible_row_count(), 1071)
        self.assertGreater(page.visible_row_count(), 0)

        page.txt_search.clear()
        combo.setCurrentIndex(0)
        self.app.processEvents()
        self.assertEqual(page.visible_row_count(), 4284)

    def test_el_formato_respeta_los_decimales(self) -> None:
        page = self.window.results_view.pages["frame_forces"]
        page.spn_decimals.setValue(2)
        self.app.processEvents()
        index = page.model.index(0, page.model.columns.index("M3 (tonf-m)"))
        self.assertEqual(page.model.data(index), "-9.21")
        page.spn_decimals.setValue(4)

    def test_los_diagramas_se_trazan_y_se_guardan(self) -> None:
        import tempfile

        view = self.window.diagram_view
        self.assertTrue(view.cmb_frame.count() > 0)
        self.assertTrue(view.diagram.has_data)
        self.assertIn("Envolvente", view.lbl_summary.text())
        with tempfile.TemporaryDirectory() as folder:
            path = view.save_png(os.path.join(folder, "d.png"))
            self.assertTrue(path and os.path.getsize(path) > 1000)

    def test_cambiar_de_barra_actualiza_el_resumen(self) -> None:
        view = self.window.diagram_view
        antes = view.lbl_summary.text()
        view.cmb_frame.setCurrentIndex(1)
        self.app.processEvents()
        self.assertNotEqual(view.lbl_summary.text(), antes)

    def test_el_arbol_del_modelo_lista_niveles_y_barras(self) -> None:
        tree = self.window.model_view.tree
        self.assertEqual(tree.topLevelItemCount(), 5)
        self.assertEqual(tree.topLevelItem(0).childCount(), 29)
        self.assertIn("Azotea", tree.topLevelItem(0).text(0))
        self.assertEqual(self.window.model_view.sections.topLevelItemCount(), 3)

    def test_las_opciones_del_panel_se_leen(self) -> None:
        options = self.window.panel.options()
        self.assertTrue(options.frame_forces)
        self.assertTrue(options.deflections)
        self.assertEqual(options.units_key, "Ton_m_C")
        self.assertAlmostEqual(options.e_value, 221359.0)
        self.assertEqual(options.e_units, "kgf/cm2")
        self.assertIn("BEAM", options.kinds)
        self.assertTrue(options.all_case_names)


if __name__ == "__main__":
    unittest.main()
