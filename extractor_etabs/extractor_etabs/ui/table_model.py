"""Modelo de tabla y filtro para los resultados.

Los resultados son muchos —un modelo mediano con veinte combinaciones deja
cientos de miles de renglones—, así que la tabla no se llena con *widgets* sino
con un :class:`QAbstractTableModel` sobre las listas que ya devolvió la capa
``core``: no se copia nada y el desplazamiento sigue siendo instantáneo.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt,
)
from PySide6.QtGui import QColor


class ResultTableModel(QAbstractTableModel):
    """Tabla de solo lectura con formato numérico configurable."""

    def __init__(self, decimals: int = 4, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._columns: List[str] = []
        self._rows: List[Sequence[Any]] = []
        self._numeric_from = 0
        self._decimals = decimals

    # ── carga ───────────────────────────────────────────────────────────────
    def set_table(self, columns: Sequence[str], rows: Sequence[Sequence[Any]],
                  numeric_from: int = 0) -> None:
        self.beginResetModel()
        self._columns = list(columns)
        self._rows = list(rows)
        self._numeric_from = numeric_from
        self.endResetModel()

    def clear(self) -> None:
        self.set_table([], [], 0)

    def set_decimals(self, decimals: int) -> None:
        if decimals == self._decimals:
            return
        self._decimals = decimals
        if self._rows:
            top = self.index(0, 0)
            bottom = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(top, bottom, [Qt.DisplayRole])

    @property
    def columns(self) -> List[str]:
        return list(self._columns)

    def row_values(self, row: int) -> Sequence[Any]:
        return self._rows[row]

    # ── interfaz de Qt ──────────────────────────────────────────────────────
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._columns[section] if section < len(self._columns) else None
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row, column = index.row(), index.column()
        if row >= len(self._rows):
            return None
        values = self._rows[row]
        value = values[column] if column < len(values) else None

        if role == Qt.DisplayRole:
            return self._format(value)
        if role == Qt.EditRole:
            return value
        if role == Qt.TextAlignmentRole:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and value is None:
            return QColor("#9aa7b8")
        return None

    def _format(self, value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "sí" if value else ""
        if isinstance(value, float):
            if value != value:                     # NaN
                return "—"
            return f"{value:,.{self._decimals}f}"
        return str(value)

    # ── copiado ─────────────────────────────────────────────────────────────
    def rows_as_text(self, rows: Sequence[int], include_header: bool = True) -> str:
        """Renglones seleccionados en texto tabulado, para pegar en Excel."""
        lines: List[str] = []
        if include_header:
            lines.append("\t".join(self._columns))
        for row in rows:
            if 0 <= row < len(self._rows):
                lines.append("\t".join(self._format(v) for v in self._rows[row]))
        return "\n".join(lines)


class MultiColumnFilter(QSortFilterProxyModel):
    """Filtra por valor exacto en varias columnas más una búsqueda libre."""

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._exact: Dict[int, str] = {}
        self._search = ""
        self.setSortRole(Qt.EditRole)

    def _invalidate(self) -> None:
        """Revalida el filtro.

        Se usa ``invalidate()`` porque las variantes ``invalidateFilter()`` e
        ``invalidateRowsFilter()`` están marcadas como obsoletas en Qt 6.11.
        """
        self.invalidate()

    def set_exact(self, column: int, value: Optional[str]) -> None:
        if value:
            self._exact[column] = value
        else:
            self._exact.pop(column, None)
        self._invalidate()

    def clear_exact(self) -> None:
        self._exact.clear()
        self._invalidate()

    def set_search(self, text: str) -> None:
        self._search = (text or "").strip().lower()
        self._invalidate()

    def filterAcceptsRow(self, source_row: int,
                         source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return True
        for column, expected in self._exact.items():
            index = model.index(source_row, column, source_parent)
            if str(model.data(index, Qt.DisplayRole)) != expected:
                return False
        if not self._search:
            return True
        for column in range(model.columnCount()):
            index = model.index(source_row, column, source_parent)
            text = str(model.data(index, Qt.DisplayRole) or "").lower()
            if self._search in text:
                return True
        return False
