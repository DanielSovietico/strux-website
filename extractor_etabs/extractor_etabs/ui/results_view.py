"""Pestañas de resultados: una tabla por tipo de cantidad, con filtros.

Cada pestaña muestra lo que ETABS entregó (o lo que trajo la tabla importada) sin
recortes: filtros por nivel, elemento y caso, búsqueda libre, orden por columna y
copiado directo a Excel.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTableView, QTabWidget, QVBoxLayout, QWidget,
)

from ..core.model import TABLE_SPECS, ResultSet, table_columns, table_rows
from .table_model import MultiColumnFilter, ResultTableModel

#: Filtros por tipo de tabla: etiqueta visible y campo del renglón.
_FILTERS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "frame_forces": (("Nivel", "story"), ("Barra", "frame"), ("Caso", "case")),
    "displacements": (("Nivel", "story"), ("Nudo", "point"), ("Caso", "case")),
    "drifts": (("Nivel", "story"), ("Caso", "case"), ("Dirección", "direction")),
    "deflections": (("Nivel", "story"), ("Barra", "frame"), ("Caso", "case")),
    "reactions": (("Caso", "case"),),
}


class ResultTablePage(QWidget):
    """Una tabla con su barra de filtros y sus botones de exportación."""

    export_requested = Signal(str, str)       # tipo de tabla, formato

    def __init__(self, kind: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._spec = TABLE_SPECS[kind]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._combos: List[Tuple[int, QComboBox]] = []
        for label, field in _FILTERS.get(kind, ()):
            column = self._spec["fields"].index(field)
            bar.addWidget(QLabel(f"{label}:"))
            combo = QComboBox()
            combo.addItem("todos", "")
            combo.setMinimumWidth(110)
            combo.currentIndexChanged.connect(self._apply_filters)
            bar.addWidget(combo)
            self._combos.append((column, combo))

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("buscar…")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self._apply_filters)
        bar.addWidget(self.txt_search, 1)

        bar.addWidget(QLabel("decimales:"))
        self.spn_decimals = QSpinBox()
        self.spn_decimals.setRange(0, 8)
        self.spn_decimals.setValue(4)
        self.spn_decimals.valueChanged.connect(
            lambda value: self.model.set_decimals(value))
        bar.addWidget(self.spn_decimals)
        layout.addLayout(bar)

        self.model = ResultTableModel()
        self.proxy = MultiColumnFilter(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(21)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.lbl_count = QLabel("sin datos")
        self.lbl_count.setObjectName("hintLabel")
        footer.addWidget(self.lbl_count, 1)
        for text, fmt in (("Copiar", "clipboard"), ("CSV…", "csv"),
                          ("Excel…", "xlsx")):
            button = QPushButton(text)
            button.clicked.connect(
                lambda _=False, f=fmt: self._on_export(f))
            footer.addWidget(button)
        layout.addLayout(footer)

        shortcut = QShortcut(QKeySequence.Copy, self.table)
        shortcut.activated.connect(lambda: self._on_export("clipboard"))

        self.proxy.rowsInserted.connect(lambda *_: self._update_count())
        self.proxy.rowsRemoved.connect(lambda *_: self._update_count())
        self.proxy.modelReset.connect(self._update_count)
        self.proxy.layoutChanged.connect(self._update_count)

    # ── datos ───────────────────────────────────────────────────────────────
    def set_result(self, result: Optional[ResultSet]) -> None:
        if result is None:
            self.model.clear()
            self._update_count()
            return
        columns = table_columns(self.kind, result.units)
        rows = table_rows(result, self.kind)
        self.model.set_table(columns, rows, self._spec["numeric_from"])
        self._refresh_filter_values(rows)
        self._update_count()
        self.table.resizeColumnsToContents()

    def _refresh_filter_values(self, rows: Sequence[Sequence[object]]) -> None:
        for column, combo in self._combos:
            values = sorted({str(row[column]) for row in rows
                             if column < len(row) and row[column] not in (None, "")})
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("todos", "")
            for value in values:
                combo.addItem(value, value)
            index = combo.findText(current)
            combo.setCurrentIndex(index if index > 0 else 0)
            combo.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self) -> None:
        for column, combo in self._combos:
            self.proxy.set_exact(column, str(combo.currentData() or ""))
        self.proxy.set_search(self.txt_search.text())
        self._update_count()

    def _update_count(self) -> None:
        shown = self.proxy.rowCount()
        total = self.model.rowCount()
        if total == 0:
            self.lbl_count.setText("sin datos para este tipo de resultado")
        elif shown == total:
            self.lbl_count.setText(f"{total:,} renglones")
        else:
            self.lbl_count.setText(f"{shown:,} de {total:,} renglones (filtrados)")

    # ── exportación ─────────────────────────────────────────────────────────
    def _on_export(self, fmt: str) -> None:
        if fmt == "clipboard":
            self._copy_selection()
            return
        self.export_requested.emit(self.kind, fmt)

    def _copy_selection(self) -> None:
        selection = self.table.selectionModel()
        if selection is None or not selection.hasSelection():
            rows = list(range(self.proxy.rowCount()))
        else:
            rows = sorted({index.row() for index in selection.selectedRows()}
                          or {index.row() for index in selection.selectedIndexes()})
        source_rows = [self.proxy.mapToSource(self.proxy.index(row, 0)).row()
                       for row in rows]
        text = self.model.rows_as_text(source_rows)
        QGuiApplication.clipboard().setText(text)

    def visible_row_count(self) -> int:
        return self.proxy.rowCount()


class ResultsView(QTabWidget):
    """Contenedor de las pestañas de resultados."""

    export_requested = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.pages: Dict[str, ResultTablePage] = {}
        for kind in TABLE_SPECS:
            page = ResultTablePage(kind)
            page.export_requested.connect(self.export_requested)
            self.pages[kind] = page
            self.addTab(page, TABLE_SPECS[kind]["title"])

    def set_result(self, result: Optional[ResultSet]) -> None:
        for kind, page in self.pages.items():
            page.set_result(result)
            index = self.indexOf(page)
            count = page.model.rowCount()
            title = TABLE_SPECS[kind]["title"]
            self.setTabText(index, f"{title}  ({count:,})" if count else title)
            self.setTabEnabled(index, count > 0 or result is None)
        for kind, page in self.pages.items():
            if page.model.rowCount():
                self.setCurrentWidget(page)
                break

    def current_kind(self) -> Optional[str]:
        widget = self.currentWidget()
        return getattr(widget, "kind", None)
