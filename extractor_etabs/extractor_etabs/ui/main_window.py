"""Ventana principal: arma el flujo completo de la aplicación.

La ventana no hace trabajo pesado: valida lo que pidió el usuario, encola la
tarea en :class:`SessionWorker` y, cuando termina, refresca las vistas con lo que
quedó en la :class:`Session`. Ese reparto es lo que mantiene la interfaz viva con
modelos grandes.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ..core import export, strux_payload
from ..core.etabs_api import unavailable_reason
from ..core.session import Session
from ..version import APP_NAME, __version__
from . import theme
from .control_panel import ControlPanel
from .diagram_view import DiagramView
from .model_view import ModelView
from .results_view import ResultsView
from .workers import SessionWorker

_E2K_FILTER = "Modelos de texto de ETABS (*.e2k *.$et *.E2K);;Todos (*)"
_TABLE_FILTER = ("Tablas exportadas (*.csv *.txt *.tsv *.xlsx *.xlsm);;"
                 "CSV (*.csv);;Excel (*.xlsx *.xlsm);;Todos (*)")
_MODEL_FILTER = ("Modelos de ETABS (*.EDB *.edb *.e2k *.$et *.ebd);;"
                 "Todos (*)")


class MainWindow(QMainWindow):
    """Ventana principal del Extractor ETABS."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__} — Strux")
        self.resize(1320, 860)
        self.setStyleSheet(theme.STYLESHEET)

        self.session = Session()
        self.worker = SessionWorker(self.session)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_job.connect(self._on_job_done)
        self.worker.failed.connect(self._on_job_failed)
        self.worker.log.connect(self._append_log)
        self.worker.busy_changed.connect(self._on_busy)
        self.worker.start()

        self._build_ui()
        self._build_menu()
        self._refresh_oapi_status()
        self._refresh_views()

    # ── construcción ────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        self.panel = ControlPanel()
        self.panel.connect_requested.connect(self.on_connect)
        self.panel.open_model_requested.connect(self.on_open_model)
        self.panel.read_model_requested.connect(self.on_read_model)
        self.panel.load_e2k_requested.connect(self.on_load_e2k)
        self.panel.import_table_requested.connect(self.on_import_table)
        self.panel.extract_requested.connect(self.on_extract)
        self.panel.deflections_requested.connect(self.on_deflections)
        self.panel.cancel_requested.connect(self.worker.cancel)
        splitter.addWidget(self.panel)

        self.tabs = QTabWidget()
        self.model_view = ModelView()
        self.results_view = ResultsView()
        self.results_view.export_requested.connect(self.on_export_table)
        self.diagram_view = DiagramView()
        self.diagram_view.save_png_requested.connect(self.on_save_png)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)

        self.tabs.addTab(self.model_view, "Modelo")
        self.tabs.addTab(self.results_view, "Resultados")
        self.tabs.addTab(self.diagram_view, "Diagramas")
        self.tabs.addTab(self.log_view, "Registro")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([350, 970])
        body_layout.addWidget(splitter)
        layout.addWidget(body, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Listo.")

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(52)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)

        brand = QLabel("Strux")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        subtitle = QLabel("Extractor <b>ETABS</b>")
        layout.addWidget(subtitle)
        layout.addStretch(1)

        self.lbl_source = QLabel()
        self.lbl_source.setObjectName("sourceChip")
        layout.addWidget(self.lbl_source)
        return header

    def _build_menu(self) -> None:
        bar = self.menuBar()

        archivo = bar.addMenu("&Archivo")
        self._add_action(archivo, "Cargar geometría de .e2k…", self.on_load_e2k,
                         QKeySequence.Open)
        self._add_action(archivo, "Importar tabla exportada…",
                         self.on_import_table)
        archivo.addSeparator()
        self._add_action(archivo, "Exportar todo a Excel…", self.on_export_xlsx,
                         QKeySequence.Save)
        self._add_action(archivo, "Exportar todo a CSV (carpeta)…",
                         self.on_export_csv_bundle)
        self._add_action(archivo, "Exportar JSON (resultados y modelo)…",
                         self.on_export_json)
        self._add_action(archivo, "Exportar JSON para el visor de vigas…",
                         self.on_export_bridge)
        archivo.addSeparator()
        self._add_action(archivo, "Salir", self.close, QKeySequence.Quit)

        etabs = bar.addMenu("&ETABS")
        self._add_action(etabs, "Conectar con ETABS abierto", self.on_connect)
        self._add_action(etabs, "Abrir modelo en ETABS…", self.on_open_model)
        self._add_action(etabs, "Leer geometría del modelo", self.on_read_model)
        self._add_action(etabs, "Extraer resultados", self.on_extract)
        etabs.addSeparator()
        self._add_action(etabs, "Desconectar", self.on_disconnect)

        ayuda = bar.addMenu("A&yuda")
        self._add_action(ayuda, "Cómo obtener las tablas de ETABS",
                         self.on_help_tables)
        self._add_action(ayuda, f"Acerca de {APP_NAME}", self.on_about)

    def _add_action(self, menu, text: str, slot,
                    shortcut: Optional[QKeySequence] = None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut is not None:
            action.setShortcut(shortcut)
        menu.addAction(action)
        return action

    # ── acciones: ETABS ─────────────────────────────────────────────────────
    def on_connect(self) -> None:
        if self._blocked_by_platform():
            return
        self.worker.submit("conectar", lambda s, p: s.connect())

    def on_open_model(self) -> None:
        if self._blocked_by_platform():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir un modelo en ETABS", "", _MODEL_FILTER)
        if not path:
            return
        units = self.panel.units_key()

        def job(session: Session, progress):
            session.open_model(path)
            return session.read_model(units, progress)

        self.worker.submit("abrir modelo", job)

    def on_read_model(self) -> None:
        if self._blocked_by_platform():
            return
        units = self.panel.units_key()
        kinds = self.panel.options().kinds
        self.worker.submit(
            "leer geometría",
            lambda s, p: s.read_model(units, p, kinds))

    def on_extract(self) -> None:
        if self._blocked_by_platform():
            return
        options = self.panel.options()
        if not options.all_case_names:
            QMessageBox.information(
                self, APP_NAME,
                "Marca al menos un caso de carga o una combinación en el paso 3.")
            return
        if not options.wants_anything():
            QMessageBox.information(
                self, APP_NAME,
                "Marca al menos una cantidad para extraer en el paso 2.")
            return
        self.worker.submit("extraer", lambda s, p: s.extract(options, p))

    def on_disconnect(self) -> None:
        self.worker.submit("desconectar", lambda s, p: s.close())

    # ── acciones: archivos ──────────────────────────────────────────────────
    def on_load_e2k(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar geometría de un .e2k", "", _E2K_FILTER)
        if path:
            self.worker.submit("cargar .e2k", lambda s, p: s.load_e2k(path))

    def on_import_table(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar una tabla exportada de ETABS", "", _TABLE_FILTER)
        if not path:
            return
        merge = False
        if self.session.result is not None and self.session.result.row_count:
            answer = QMessageBox.question(
                self, APP_NAME,
                "Ya hay resultados cargados.\n\n¿Agregar los de esta tabla a los "
                "existentes? («No» los reemplaza.)",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel:
                return
            merge = answer == QMessageBox.Yes
        self.worker.submit("importar tabla",
                           lambda s, p: s.load_table(path, merge=merge))

    def on_deflections(self) -> None:
        if self.session.result is None:
            QMessageBox.information(
                self, APP_NAME,
                "Primero extrae resultados de ETABS o importa una tabla con "
                "momentos (M3).")
            return
        options = self.panel.options()
        self.worker.submit("deflexiones",
                           lambda s, p: s.add_deflections(options, p))

    # ── exportación ─────────────────────────────────────────────────────────
    def on_export_table(self, kind: str, fmt: str) -> None:
        result = self.session.result
        if result is None:
            return
        if fmt == "csv":
            path, _ = QFileDialog.getSaveFileName(
                self, "Guardar tabla en CSV", f"{kind}.csv", "CSV (*.csv)")
            if path:
                self._guard(lambda: export.export_csv(result, kind, path), path)
        elif fmt == "xlsx":
            self.on_export_xlsx()

    def on_export_xlsx(self) -> None:
        result = self.session.result
        if result is None:
            self._need_results()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", "extraccion_etabs.xlsx",
            "Excel (*.xlsx)")
        if path:
            self._guard(
                lambda: export.export_xlsx(result, path, self.session.model), path)

    def on_export_csv_bundle(self) -> None:
        result = self.session.result
        if result is None:
            self._need_results()
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Carpeta donde guardar los CSV")
        if directory:
            self._guard(lambda: ", ".join(
                os.path.basename(p)
                for p in export.export_csv_bundle(result, directory)), directory)

    def on_export_json(self) -> None:
        result = self.session.result
        if result is None:
            self._need_results()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar JSON", "extraccion_etabs.json", "JSON (*.json)")
        if path:
            self._guard(
                lambda: export.export_json(result, path, self.session.model), path)

    def on_export_bridge(self) -> None:
        if self.session.model is None and self.session.result is None:
            self._need_results()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar JSON para el visor de vigas", "puente_strux.json",
            "JSON (*.json)")
        if path:
            self._guard(lambda: strux_payload.write_bridge_json(
                path, self.session.model, self.session.result), path)

    def on_save_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar los diagramas como imagen", "diagramas.png",
            "PNG (*.png)")
        if not path:
            return
        saved = self.diagram_view.save_png(path)
        if saved is None:
            QMessageBox.information(self, APP_NAME,
                                    "No hay diagramas trazados que guardar.")
        else:
            self._append_log(f"Imagen guardada: {saved}")
            self.statusBar().showMessage(f"Imagen guardada en {saved}", 6000)

    def _guard(self, action, target: str) -> None:
        """Ejecuta una exportación informando el resultado sin tumbar la app."""
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            action()
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"No se pudo exportar:\n\n{exc}")
            self._append_log(f"Error al exportar: {exc}")
        else:
            self._append_log(f"Exportado: {target}")
            self.statusBar().showMessage(f"Exportado a {target}", 6000)
        finally:
            QApplication.restoreOverrideCursor()

    def _need_results(self) -> None:
        QMessageBox.information(
            self, APP_NAME,
            "Todavía no hay resultados que exportar: extrae de ETABS o importa "
            "una tabla.")

    # ── ayuda ───────────────────────────────────────────────────────────────
    def on_help_tables(self) -> None:
        QMessageBox.information(
            self, "Cómo obtener las tablas de ETABS",
            "En ETABS: <b>File ▸ Export ▸ Tables to Excel / CSV</b> y elige<br><br>"
            "• <b>Element Forces - Beams</b> (y <i>- Columns</i>) → momentos, "
            "cortantes, axial y torsión por estación.<br>"
            "• <b>Joint Displacements</b> → desplazamientos y rotaciones.<br>"
            "• <b>Story Drifts</b> → derivas de entrepiso.<br>"
            "• <b>Base Reactions</b> → reacciones globales.<br><br>"
            "Selecciona antes las combinaciones que te interesan en "
            "<i>Display ▸ Load Cases/Combinations</i>. La geometría puede venir "
            "de <b>File ▸ Export ▸ ETABS .e2k Text File</b>.")

    def on_about(self) -> None:
        QMessageBox.about(
            self, f"Acerca de {APP_NAME}",
            f"<b>{APP_NAME}</b> {__version__}<br><br>"
            "Extrae momentos, cortantes, desplazamientos y derivas de un modelo "
            "de ETABS por tres vías: la OAPI del programa abierto, un archivo "
            ".e2k y las tablas exportadas.<br><br>"
            "Las deflexiones a lo largo de la trabe son un cálculo propio "
            "(doble integración de M3/EI); todo lo demás es lectura directa de "
            "ETABS.<br><br>Strux · " + str(__version__))

    # ── reacciones del hilo de trabajo ──────────────────────────────────────
    def _on_progress(self, message: str, done: int, total: int) -> None:
        self.panel.set_progress(message, done, total)
        self.statusBar().showMessage(message)

    def _on_busy(self, busy: bool) -> None:
        self.panel.set_busy(busy)
        if not busy:
            self._refresh_oapi_status()

    def _on_job_done(self, name: str, _result: object) -> None:
        self._refresh_views()
        self.statusBar().showMessage(f"«{name}» terminó.", 5000)
        if name in ("extraer", "importar tabla") and self.session.result is not None:
            if self.session.result.row_count:
                self.tabs.setCurrentWidget(self.results_view)

    def _on_job_failed(self, name: str, message: str) -> None:
        self._refresh_views()
        if "cancelada" in message.lower():
            self.statusBar().showMessage(message, 5000)
            return
        QMessageBox.warning(self, APP_NAME, f"No se pudo {name}:\n\n{message}")

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    # ── refresco de vistas ──────────────────────────────────────────────────
    def _refresh_views(self) -> None:
        session = self.session
        self.lbl_source.setText(session.source_label)
        self.model_view.set_model(session.model, session.result)
        self.results_view.set_result(session.result)
        self.diagram_view.set_data(session.result, session.model)
        if session.model is not None:
            self.panel.populate_model(session.model)
            self.panel.set_units_key(session.model.info.units.key
                                     or self.panel.units_key())
        elif session.result is not None and session.result.cases:
            self.panel.populate_cases_from_names(session.result.cases)

    def _refresh_oapi_status(self) -> None:
        reason = unavailable_reason()
        if reason:
            self.panel.set_oapi_status(reason, "warn")
            self.panel.set_oapi_enabled(False)
            return
        if self.session.can_extract:
            self.panel.set_oapi_status(
                "Conectado a ETABS. Lee la geometría y extrae los resultados.",
                "ok")
        else:
            self.panel.set_oapi_status(
                "ETABS disponible en esta máquina. Conéctate al modelo abierto "
                "o abre un archivo .EDB.", "info")
        self.panel.set_oapi_enabled(True)

    def _blocked_by_platform(self) -> bool:
        reason = unavailable_reason()
        if reason:
            QMessageBox.information(self, APP_NAME, reason)
            return True
        return False

    # ── cierre ──────────────────────────────────────────────────────────────
    def closeEvent(self, event) -> None:      # noqa: N802 (API de Qt)
        self.worker.cancel()
        try:
            if self.session.connection is not None:
                self.worker.submit("desconectar", lambda s, p: s.close())
        finally:
            self.worker.shutdown()
        event.accept()
