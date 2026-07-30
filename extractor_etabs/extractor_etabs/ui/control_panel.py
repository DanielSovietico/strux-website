"""Columna de control: fuente de datos, qué extraer y casos de carga.

Es un panel «tonto»: no abre diálogos ni toca ETABS, solo emite señales y sabe
armar unas :class:`ExtractionOptions` con lo que el usuario marcó. Así la ventana
principal conserva el control del flujo y el panel se puede probar aparte.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..core.extractors import ExtractionOptions
from ..core.model import StructuralModel
from ..core.units import UNIT_CHOICES
from . import theme

_E_UNITS = ("kgf/cm2", "tonf/cm2", "MPa", "kN/cm2", "kip/in2", "psi")


def _wrapped(label: QLabel, object_name: str = "") -> QLabel:
    """Etiqueta multilínea que puede encogerse con el panel.

    Una ``QLabel`` con ``wordWrap`` pide de ancho lo que mide su texto en una
    sola línea, y dentro de un área de desplazamiento eso recorta el texto en
    lugar de partirlo; con la política horizontal ``Ignored`` se ajusta al ancho
    disponible.
    """
    label.setWordWrap(True)
    if object_name:
        label.setObjectName(object_name)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.MinimumExpanding)
    label.setMinimumWidth(120)
    return label


class ControlPanel(QWidget):
    """Panel izquierdo con los tres pasos del flujo de trabajo."""

    connect_requested = Signal()
    open_model_requested = Signal()
    read_model_requested = Signal()
    load_e2k_requested = Signal()
    import_table_requested = Signal()
    extract_requested = Signal()
    deflections_requested = Signal()
    cancel_requested = Signal()
    units_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(368)
        self.setMaximumWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # Sin barra horizontal: el panel se adapta a lo ancho y solo se
        # desplaza a lo alto, que es como se usa.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 8, 2)
        layout.setSpacing(10)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        layout.addWidget(self._build_source_group())
        layout.addWidget(self._build_what_group())
        layout.addWidget(self._build_cases_group())
        layout.addStretch(1)

        outer.addWidget(self._build_action_bar())

    # ── 1 · fuente ──────────────────────────────────────────────────────────
    def _build_source_group(self) -> QGroupBox:
        group = QGroupBox("1 · Fuente de datos")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self.oapi_status = _wrapped(QLabel(), "statusBanner")
        layout.addWidget(self.oapi_status)

        self.btn_connect = QPushButton("Conectar con ETABS abierto")
        self.btn_connect.setObjectName("primary")
        self.btn_connect.clicked.connect(self.connect_requested)
        layout.addWidget(self.btn_connect)

        self.btn_open_model = QPushButton("Abrir modelo en ETABS…  (.EDB)")
        self.btn_open_model.clicked.connect(self.open_model_requested)
        layout.addWidget(self.btn_open_model)

        self.btn_read_model = QPushButton("Leer geometría del modelo")
        self.btn_read_model.clicked.connect(self.read_model_requested)
        layout.addWidget(self.btn_read_model)

        separator = QLabel("— o sin ETABS instalado —")
        separator.setObjectName("hintLabel")
        separator.setAlignment(Qt.AlignCenter)
        layout.addWidget(separator)

        self.btn_e2k = QPushButton("Cargar geometría de .e2k / .$et…")
        self.btn_e2k.clicked.connect(self.load_e2k_requested)
        layout.addWidget(self.btn_e2k)

        self.btn_table = QPushButton("Importar tabla exportada…  (CSV/XLSX)")
        self.btn_table.clicked.connect(self.import_table_requested)
        layout.addWidget(self.btn_table)
        return group

    # ── 2 · qué extraer ─────────────────────────────────────────────────────
    def _build_what_group(self) -> QGroupBox:
        group = QGroupBox("2 · Qué extraer")
        layout = QVBoxLayout(group)
        layout.setSpacing(5)

        self.chk_forces = QCheckBox("Momentos, cortantes, axial y torsión")
        self.chk_forces.setChecked(True)
        self.chk_displ = QCheckBox("Desplazamientos y rotaciones de nudos")
        self.chk_displ.setChecked(True)
        self.chk_drifts = QCheckBox("Derivas de entrepiso")
        self.chk_drifts.setChecked(True)
        self.chk_reactions = QCheckBox("Reacciones en la base")
        self.chk_defl = QCheckBox("Deflexiones de trabes (calculadas de M3/EI)")
        self.chk_defl.setChecked(True)
        for widget in (self.chk_forces, self.chk_displ, self.chk_drifts,
                       self.chk_reactions, self.chk_defl):
            layout.addWidget(widget)

        kinds = QHBoxLayout()
        kinds.setSpacing(8)
        kinds.addWidget(QLabel("Barras:"))
        self.chk_beams = QCheckBox("trabes")
        self.chk_beams.setChecked(True)
        self.chk_columns = QCheckBox("columnas")
        self.chk_columns.setChecked(True)
        self.chk_braces = QCheckBox("diagonales")
        for widget in (self.chk_beams, self.chk_columns, self.chk_braces):
            kinds.addWidget(widget)
        kinds.addStretch(1)
        layout.addLayout(kinds)

        units_row = QHBoxLayout()
        units_row.addWidget(QLabel("Unidades:"))
        self.cmb_units = QComboBox()
        for key, label in UNIT_CHOICES:
            self.cmb_units.addItem(label, key)
        self.cmb_units.currentIndexChanged.connect(
            lambda _: self.units_changed.emit(self.units_key()))
        units_row.addWidget(self.cmb_units, 1)
        layout.addLayout(units_row)

        e_row = QHBoxLayout()
        e_row.setSpacing(5)
        e_row.addWidget(QLabel("E ="))
        self.spn_e = QDoubleSpinBox()
        self.spn_e.setRange(1.0, 1e9)
        self.spn_e.setDecimals(0)
        self.spn_e.setValue(221359.0)          # 14000·√250, concreto clase 1
        self.spn_e.setGroupSeparatorShown(True)
        self.spn_e.setToolTip(
            "Módulo de elasticidad para calcular deflexiones. El valor por "
            "omisión corresponde a 14000·√f'c con f'c = 250 kg/cm².")
        e_row.addWidget(self.spn_e, 1)
        self.cmb_e_units = QComboBox()
        self.cmb_e_units.addItems(_E_UNITS)
        self.cmb_e_units.setMinimumWidth(92)
        e_row.addWidget(self.cmb_e_units, 0)
        layout.addLayout(e_row)

        inertia_row = QHBoxLayout()
        inertia_row.setSpacing(5)
        inertia_row.addWidget(QLabel("Inercia para deflexiones  ×"))
        self.spn_inertia = QDoubleSpinBox()
        self.spn_inertia.setRange(0.05, 1.0)
        self.spn_inertia.setSingleStep(0.05)
        self.spn_inertia.setValue(1.0)
        self.spn_inertia.setToolTip(
            "Factor sobre la inercia bruta: 1.00 usa Ig; valores menores "
            "representan una inercia efectiva agrietada.")
        inertia_row.addWidget(self.spn_inertia, 1)
        layout.addLayout(inertia_row)

        self.chk_run = QCheckBox("Correr el análisis en ETABS si hace falta")
        self.chk_run.setToolTip(
            "Si el modelo no está bloqueado, ETABS no tiene resultados. Con "
            "esta casilla la aplicación pide correr el análisis antes de leer.")
        layout.addWidget(self.chk_run)

        note = _wrapped(QLabel("La deflexión es un cálculo de esta aplicación a "
                               "partir de M3; los desplazamientos de nudos y las "
                               "derivas los reporta ETABS."), "hintLabel")
        layout.addWidget(note)
        return group

    # ── 3 · casos y niveles ─────────────────────────────────────────────────
    def _build_cases_group(self) -> QGroupBox:
        group = QGroupBox("3 · Casos de carga y niveles")
        layout = QVBoxLayout(group)
        layout.setSpacing(5)

        self.lst_cases = QListWidget()
        self.lst_cases.setSelectionMode(QListWidget.NoSelection)
        self.lst_cases.setMinimumHeight(130)
        self.lst_cases.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.lst_cases, 1)

        buttons = QHBoxLayout()
        for text, action in (("Todos", self._check_all_cases),
                             ("Ninguno", self._uncheck_all_cases),
                             ("Solo combinaciones", self._only_combos)):
            button = QPushButton(text)
            button.clicked.connect(action)
            buttons.addWidget(button)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("Niveles (sin marcar = todos):"))
        self.lst_stories = QListWidget()
        self.lst_stories.setSelectionMode(QListWidget.NoSelection)
        self.lst_stories.setMaximumHeight(110)
        layout.addWidget(self.lst_stories)
        return group

    # ── barra de acción ─────────────────────────────────────────────────────
    def _build_action_bar(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(2, 0, 8, 2)
        layout.setSpacing(6)

        self.btn_extract = QPushButton("Extraer de ETABS")
        self.btn_extract.setObjectName("primary")
        self.btn_extract.clicked.connect(self.extract_requested)
        layout.addWidget(self.btn_extract)

        row = QHBoxLayout()
        self.btn_defl = QPushButton("Recalcular deflexiones")
        self.btn_defl.clicked.connect(self.deflections_requested)
        row.addWidget(self.btn_defl, 1)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.cancel_requested)
        self.btn_cancel.setEnabled(False)
        row.addWidget(self.btn_cancel)
        layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%  —  listo")
        layout.addWidget(self.progress)
        return box

    # ── estado ──────────────────────────────────────────────────────────────
    def set_oapi_status(self, text: str, kind: str = "info") -> None:
        self.oapi_status.setText(text)
        self.oapi_status.setStyleSheet(theme.banner_style(kind))

    def set_oapi_enabled(self, enabled: bool) -> None:
        for button in (self.btn_connect, self.btn_open_model, self.btn_read_model,
                       self.btn_extract):
            button.setEnabled(enabled)

    def set_busy(self, busy: bool) -> None:
        for button in (self.btn_connect, self.btn_open_model, self.btn_read_model,
                       self.btn_e2k, self.btn_table, self.btn_extract,
                       self.btn_defl):
            button.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        if not busy:
            self.progress.setValue(0)
            self.progress.setFormat("%p%  —  listo")

    def set_progress(self, message: str, done: int, total: int) -> None:
        total = max(total, 1)
        self.progress.setRange(0, total)
        self.progress.setValue(min(done, total))
        self.progress.setFormat(f"%p%  —  {message}")

    def units_key(self) -> str:
        return str(self.cmb_units.currentData() or "Ton_m_C")

    def set_units_key(self, key: str) -> None:
        index = self.cmb_units.findData(key)
        if index >= 0:
            self.cmb_units.setCurrentIndex(index)

    # ── casos y niveles ─────────────────────────────────────────────────────
    def populate_model(self, model: Optional[StructuralModel]) -> None:
        """Vuelca los casos, combinaciones y niveles del modelo en las listas."""
        previous = set(self.checked_cases() + self.checked_combos())
        self.lst_cases.clear()
        self.lst_stories.clear()
        if model is None:
            return

        for name in model.load_cases:
            self._add_case(name, "case", "Caso")
        for name in model.load_combos:
            self._add_case(name, "combo", "Combo")
        if previous:
            for index in range(self.lst_cases.count()):
                item = self.lst_cases.item(index)
                item.setCheckState(Qt.Checked if item.data(Qt.UserRole + 1) in previous
                                   else Qt.Unchecked)
        elif self.lst_cases.count():
            self._only_combos() if model.load_combos else self._check_all_cases()

        for story in model.stories:
            item = QListWidgetItem(story.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.lst_stories.addItem(item)

    def populate_cases_from_names(self, names: List[str]) -> None:
        """Casos venidos de una tabla importada (no hay catálogo del modelo)."""
        self.lst_cases.clear()
        for name in names:
            self._add_case(name, "combo", "Tabla")
        self._check_all_cases()

    def _add_case(self, name: str, kind: str, tag: str) -> None:
        item = QListWidgetItem(f"{tag} · {name}")
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked)
        item.setData(Qt.UserRole, kind)
        item.setData(Qt.UserRole + 1, name)
        self.lst_cases.addItem(item)

    def _iter_cases(self):
        for index in range(self.lst_cases.count()):
            yield self.lst_cases.item(index)

    def _check_all_cases(self) -> None:
        for item in self._iter_cases():
            item.setCheckState(Qt.Checked)

    def _uncheck_all_cases(self) -> None:
        for item in self._iter_cases():
            item.setCheckState(Qt.Unchecked)

    def _only_combos(self) -> None:
        for item in self._iter_cases():
            item.setCheckState(Qt.Checked if item.data(Qt.UserRole) == "combo"
                               else Qt.Unchecked)

    def checked_cases(self) -> List[str]:
        return [item.data(Qt.UserRole + 1) for item in self._iter_cases()
                if item.checkState() == Qt.Checked
                and item.data(Qt.UserRole) == "case"]

    def checked_combos(self) -> List[str]:
        return [item.data(Qt.UserRole + 1) for item in self._iter_cases()
                if item.checkState() == Qt.Checked
                and item.data(Qt.UserRole) != "case"]

    def checked_stories(self) -> List[str]:
        return [self.lst_stories.item(i).text()
                for i in range(self.lst_stories.count())
                if self.lst_stories.item(i).checkState() == Qt.Checked]

    # ── opciones ────────────────────────────────────────────────────────────
    def options(self) -> ExtractionOptions:
        kinds: List[str] = []
        if self.chk_beams.isChecked():
            kinds.append("BEAM")
        if self.chk_columns.isChecked():
            kinds.append("COLUMN")
        if self.chk_braces.isChecked():
            kinds.append("BRACE")
        return ExtractionOptions(
            cases=self.checked_cases(),
            combos=self.checked_combos(),
            frame_forces=self.chk_forces.isChecked(),
            displacements=self.chk_displ.isChecked(),
            drifts=self.chk_drifts.isChecked(),
            reactions=self.chk_reactions.isChecked(),
            deflections=self.chk_defl.isChecked(),
            stories=self.checked_stories(),
            kinds=kinds or ["BEAM"],
            units_key=self.units_key(),
            e_value=float(self.spn_e.value()),
            e_units=self.cmb_e_units.currentText(),
            inertia_factor=float(self.spn_inertia.value()),
            run_analysis_if_unlocked=self.chk_run.isChecked(),
        )
