"""Pestaña «Modelo»: qué se leyó, qué faltó y el inventario de barras."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core.model import ResultSet, StructuralModel
from . import theme

_KIND_LABEL = {"BEAM": "trabe", "COLUMN": "columna", "BRACE": "diagonal",
               "OTHER": "otra"}


class ModelView(QWidget):
    """Resumen del modelo: procedencia, conteos, faltantes y barras por nivel."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.lbl_title = QLabel("Sin modelo cargado")
        self.lbl_title.setObjectName("titleLabel")
        layout.addWidget(self.lbl_title)

        self.lbl_info = QLabel("Conéctate a ETABS o carga un .e2k para empezar.")
        self.lbl_info.setObjectName("hintLabel")
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

        self.lbl_notes = QLabel()
        self.lbl_notes.setObjectName("statusBanner")
        self.lbl_notes.setWordWrap(True)
        self.lbl_notes.setVisible(False)
        layout.addWidget(self.lbl_notes)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nivel / barra", "Tipo", "Sección",
                                   "Longitud", "Eje", "De", "A"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        splitter.addWidget(self.tree)

        self.sections = QTreeWidget()
        self.sections.setHeaderLabels(["Sección", "Material", "b (cm)",
                                       "h (cm)", "I (cm⁴)", "Dimensiones de"])
        self.sections.setAlternatingRowColors(True)
        self.sections.setEditTriggers(QAbstractItemView.NoEditTriggers)
        splitter.addWidget(self.sections)
        splitter.setSizes([620, 420])

    def set_model(self, model: Optional[StructuralModel],
                  result: Optional[ResultSet] = None) -> None:
        self.tree.clear()
        self.sections.clear()
        if model is None:
            self.lbl_title.setText("Sin modelo cargado")
            self.lbl_info.setText(
                "Conéctate a ETABS o carga un .e2k para empezar.")
            self.lbl_notes.setVisible(False)
            return

        origin = {"oapi": "ETABS (OAPI)", "e2k": "archivo .e2k"}.get(
            model.info.source, model.info.source)
        self.lbl_title.setText(model.info.title or model.info.file or "Modelo")
        counts = model.counts()
        self.lbl_info.setText(
            f"{model.info.program or 'ETABS'} {model.info.version or ''} · "
            f"origen: {origin} · unidades: {model.info.units.label} · "
            + " · ".join(f"{k}: {v}" for k, v in counts.items()))

        notes = []
        for item in model.missing:
            notes.append(f"Falta: {item}")
        for item in model.warnings[:12]:
            notes.append(f"Aviso: {item}")
        if len(model.warnings) > 12:
            notes.append(f"… y {len(model.warnings) - 12} avisos más "
                         "(pestaña Registro).")
        if model.error:
            notes.insert(0, f"Error: {model.error}")
        if notes:
            self.lbl_notes.setText("\n".join(notes))
            self.lbl_notes.setStyleSheet(theme.banner_style(
                "error" if model.error else "warn"))
            self.lbl_notes.setVisible(True)
        else:
            self.lbl_notes.setVisible(False)

        with_results = set()
        if result is not None:
            with_results = {row.frame for row in result.frame_forces}

        by_story = model.frames_by_story()
        for story in model.stories:
            frames = by_story.get(story.name, [])
            elevation = ("—" if story.elevation is None
                         else f"{story.elevation:,.3f}")
            node = QTreeWidgetItem([
                f"{story.name}  (cota {elevation} {model.info.units.length})",
                f"{len(frames)} barras", "", "", "", "", ""])
            node.setFirstColumnSpanned(False)
            self.tree.addTopLevelItem(node)
            for frame in frames:
                length = frame.length
                child = QTreeWidgetItem([
                    frame.display_name,
                    _KIND_LABEL.get(frame.kind, frame.kind.lower()),
                    frame.section or "—",
                    "—" if length is None else f"{length:,.3f}",
                    frame.grid_line or "—",
                    frame.grid_i or "—",
                    frame.grid_j or "—"])
                if frame.name in with_results:
                    child.setForeground(0, Qt.darkGreen)
                    child.setToolTip(0, "Tiene resultados extraídos")
                node.addChild(child)
        # Los niveles sin correspondencia con la lista de pisos (por ejemplo un
        # .e2k con asignaciones a niveles que no declaró) también se muestran.
        known = {s.name for s in model.stories}
        for story_name, frames in by_story.items():
            if story_name in known:
                continue
            node = QTreeWidgetItem([story_name, f"{len(frames)} barras",
                                    "", "", "", "", ""])
            self.tree.addTopLevelItem(node)

        if self.tree.topLevelItemCount():
            self.tree.topLevelItem(0).setExpanded(True)
        for column in range(1, self.tree.columnCount()):
            self.tree.resizeColumnToContents(column)

        for name, section in sorted(model.sections.items()):
            source = {"api": "ETABS", "e2k": "archivo", "nombre": "su nombre"}.get(
                section.dim_source or "", "—")
            inertia = section.inertia_cm4
            item = QTreeWidgetItem([
                name, section.material or "—",
                "—" if section.b_cm is None else f"{section.b_cm:,.1f}",
                "—" if section.h_cm is None else f"{section.h_cm:,.1f}",
                "—" if inertia is None else f"{inertia:,.0f}", source])
            if section.dim_source == "nombre":
                item.setForeground(5, Qt.darkYellow)
            self.sections.addTopLevelItem(item)
        for column in range(self.sections.columnCount()):
            self.sections.resizeColumnToContents(column)
