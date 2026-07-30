"""Pestaña «Diagramas»: momento, cortante y deflexión de una barra y un caso.

Al elegir barra y caso se trazan las tres curvas con los mismos datos que ya
están en las tablas —no se recalcula nada aparte— y se resume la envolvente de
la barra sobre todos los casos extraídos.
"""

from __future__ import annotations

import re
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..core.model import ResultSet, StructuralModel
from . import theme
from .diagram_widget import DiagramWidget, Series


class DiagramView(QWidget):
    """Selectores + dibujo + resumen de envolvente."""

    save_png_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._result: Optional[ResultSet] = None
        self._model: Optional[StructuralModel] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QLabel("Nivel:"))
        self.cmb_story = QComboBox()
        self.cmb_story.setMinimumWidth(120)
        self.cmb_story.currentIndexChanged.connect(self._on_story_changed)
        bar.addWidget(self.cmb_story)

        bar.addWidget(QLabel("Barra:"))
        self.cmb_frame = QComboBox()
        self.cmb_frame.setMinimumWidth(130)
        self.cmb_frame.currentIndexChanged.connect(self._refresh)
        bar.addWidget(self.cmb_frame)

        bar.addWidget(QLabel("Caso:"))
        self.cmb_case = QComboBox()
        self.cmb_case.setMinimumWidth(180)
        self.cmb_case.currentIndexChanged.connect(self._refresh)
        bar.addWidget(self.cmb_case)

        self.chk_m = QCheckBox("M3")
        self.chk_v = QCheckBox("V2")
        self.chk_d = QCheckBox("deflexión")
        for widget in (self.chk_m, self.chk_v, self.chk_d):
            widget.setChecked(True)
            widget.toggled.connect(self._refresh)
            bar.addWidget(widget)

        self.chk_flip = QCheckBox("M positivo hacia abajo")
        self.chk_flip.setChecked(True)
        self.chk_flip.setToolTip(
            "Convención de dibujo: con la casilla marcada el momento positivo "
            "se traza del lado de la tensión, como en los diagramas de mano.")
        self.chk_flip.toggled.connect(self._refresh)
        bar.addWidget(self.chk_flip)

        bar.addStretch(1)
        self.btn_png = QPushButton("Guardar PNG…")
        self.btn_png.clicked.connect(self.save_png_requested)
        bar.addWidget(self.btn_png)
        layout.addLayout(bar)

        self.lbl_summary = QLabel()
        self.lbl_summary.setObjectName("statusBanner")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(theme.banner_style("info"))
        layout.addWidget(self.lbl_summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.diagram = DiagramWidget()
        scroll.setWidget(self.diagram)
        layout.addWidget(scroll, 1)

    # ── datos ───────────────────────────────────────────────────────────────
    def set_data(self, result: Optional[ResultSet],
                 model: Optional[StructuralModel]) -> None:
        self._result, self._model = result, model
        self.cmb_story.blockSignals(True)
        self.cmb_story.clear()
        if result is not None:
            stories = sorted({story for story, _ in result.frames_present()})
            self.cmb_story.addItems(stories or ["(sin nivel)"])
        self.cmb_story.blockSignals(False)

        self.cmb_case.blockSignals(True)
        self.cmb_case.clear()
        if result is not None:
            self.cmb_case.addItems(sorted(result.cases))
        self.cmb_case.blockSignals(False)

        self._on_story_changed()

    def _on_story_changed(self) -> None:
        self.cmb_frame.blockSignals(True)
        self.cmb_frame.clear()
        if self._result is not None:
            story = self.cmb_story.currentText()
            frames = sorted({frame for st, frame in self._result.frames_present()
                             if st == story or story == "(sin nivel)"},
                            key=_natural_key)
            self.cmb_frame.addItems(frames)
        self.cmb_frame.blockSignals(False)
        self._refresh()

    def current_selection(self) -> tuple:
        return (self.cmb_story.currentText(), self.cmb_frame.currentText(),
                self.cmb_case.currentText())

    def _refresh(self) -> None:
        result = self._result
        if result is None or not self.cmb_frame.count() or not self.cmb_case.count():
            self.diagram.clear()
            self.lbl_summary.setText(
                "Extrae resultados (o importa una tabla) para ver diagramas.")
            return

        story, frame_name, case = self.current_selection()
        rows = result.series(story, frame_name, case)
        units = result.units
        series: List[Series] = []

        if self.chk_m.isChecked():
            series.append(Series(
                title="Momento flexionante M3", unit=units.moment,
                xs=[r.station for r in rows],
                ys=[r.M3 if r.M3 is not None else 0.0 for r in rows],
                color=theme.DIAGRAM_M,
                positive_down=self.chk_flip.isChecked(),
                note="La tabla no trae M3 para esta barra y caso."))
        if self.chk_v.isChecked():
            has_v2 = any(r.V2 is not None for r in rows)
            series.append(Series(
                title="Fuerza cortante V2", unit=units.force,
                xs=[r.station for r in rows] if has_v2 else [],
                ys=[r.V2 if r.V2 is not None else 0.0 for r in rows] if has_v2 else [],
                color=theme.DIAGRAM_V, positive_down=False,
                note="No hay columna V2 en los datos importados."))
        if self.chk_d.isChecked():
            deflections = [d for d in result.deflections
                           if d.frame == frame_name and d.case == case
                           and (not story or d.story == story)]
            deflections.sort(key=lambda d: d.station)
            series.append(Series(
                title="Deflexión calculada (M3/EI)", unit=units.length,
                xs=[d.station for d in deflections],
                ys=[d.deflection or 0.0 for d in deflections],
                color=theme.DIAGRAM_D, positive_down=True,
                note=("Sin deflexión para esta barra: marca «Deflexiones» y "
                      "recalcula, o revisa que la sección tenga dimensiones.")))

        frame = self._model.frame(frame_name) if self._model else None
        subtitle_parts = [f"{story} · {frame_name} · {case}"]
        if frame is not None:
            if frame.section:
                subtitle_parts.append(f"sección {frame.section}")
            if frame.length:
                subtitle_parts.append(f"L = {frame.length:,.3f} {units.length}")
        self.diagram.set_series(series, " · ".join(subtitle_parts), units.length)
        self._update_summary(story, frame_name, rows)

    def _update_summary(self, story: str, frame_name: str, rows: list) -> None:
        result = self._result
        if result is None:
            return
        envelope = result.envelope(story, frame_name)
        units = result.units

        def fmt(value: Optional[float], unit: str) -> str:
            return "—" if value is None else f"{value:,.3f} {unit}"

        pieces = [
            f"Envolvente de {frame_name} sobre {len(result.cases)} caso(s): "
            f"M3 máx {fmt(envelope['M3_max'], units.moment)}, "
            f"M3 mín {fmt(envelope['M3_min'], units.moment)}, "
            f"V2 máx {fmt(envelope['V2_max'], units.force)}, "
            f"V2 mín {fmt(envelope['V2_min'], units.force)}",
        ]
        peaks = [d for d in result.deflections
                 if d.frame == frame_name and d.is_max
                 and (not story or d.story == story)]
        if peaks:
            worst = max(peaks, key=lambda d: abs(d.deflection or 0.0))
            ratio = ("—" if not worst.deflection or not worst.span
                     else f"L/{worst.span / abs(worst.deflection):,.0f}")
            pieces.append(
                f"Deflexión máxima calculada {worst.deflection:,.4f} "
                f"{units.length} ({ratio}) en «{worst.case}»")
        if not rows:
            pieces.append("Esta barra no tiene renglones para el caso elegido.")
        self.lbl_summary.setText("   |   ".join(pieces))

    def save_png(self, path: str) -> Optional[str]:
        if not self.diagram.has_data:
            return None
        return self.diagram.save_png(path)


def _natural_key(text: str) -> tuple:
    """Ordena B2 antes que B10 (los nombres de ETABS son alfanuméricos)."""
    parts = re.split(r"(\d+)", str(text))
    return tuple(int(p) if p.isdigit() else p.lower() for p in parts)
