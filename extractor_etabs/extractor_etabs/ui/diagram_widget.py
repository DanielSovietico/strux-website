"""Diagramas de momento, cortante y deflexión dibujados con QPainter.

Se dibuja a mano en lugar de arrastrar una biblioteca de graficación: son
diagramas de una variable sobre la longitud de la barra, el archivo pesa poco y
la aplicación queda con una sola dependencia (PySide6), lo que simplifica
empaquetarla para un colega que no usa Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme


@dataclass
class Series:
    """Una curva sobre la longitud de la barra."""

    title: str
    unit: str
    xs: List[float] = field(default_factory=list)
    ys: List[float] = field(default_factory=list)
    color: str = theme.DIAGRAM_M
    positive_down: bool = True       # convención de dibujo (momento hacia abajo)
    note: Optional[str] = None

    @property
    def empty(self) -> bool:
        return len(self.xs) < 2 or len(self.ys) < 2


class DiagramWidget(QWidget):
    """Dibuja una o varias curvas, una debajo de otra, con eje común."""

    MARGIN_LEFT = 62
    MARGIN_RIGHT = 18
    MARGIN_TOP = 24
    MARGIN_BOTTOM = 26
    PANEL_HEIGHT = 150

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._series: List[Series] = []
        self._subtitle = ""
        self._length_unit = "m"
        self.setMinimumHeight(self.PANEL_HEIGHT + 20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAutoFillBackground(True)

    # ── datos ───────────────────────────────────────────────────────────────
    def set_series(self, series: Sequence[Series], subtitle: str = "",
                   length_unit: str = "m") -> None:
        self._series = [s for s in series]
        self._subtitle = subtitle
        self._length_unit = length_unit
        self.setMinimumHeight(max(1, len(self._series)) * self.PANEL_HEIGHT + 30)
        self.update()

    def clear(self) -> None:
        self.set_series([], "")

    @property
    def has_data(self) -> bool:
        return any(not s.empty for s in self._series)

    def save_png(self, path: str, scale: int = 2) -> str:
        """Guarda el dibujo actual como imagen (para pegar en la memoria)."""
        pixmap = QPixmap(self.width() * scale, self.height() * scale)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(QColor("#ffffff"))
        painter = QPainter(pixmap)
        painter.scale(scale, scale)
        self._paint(painter, self.width(), self.height())
        painter.end()
        pixmap.save(path, "PNG")
        return path

    # ── dibujo ──────────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:       # noqa: N802 (API de Qt)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        self._paint(painter, self.width(), self.height())
        painter.end()

    def _paint(self, painter: QPainter, width: int, height: int) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        if not self._series:
            self._draw_placeholder(painter, width, height,
                                   "Elige un nivel, una barra y un caso para "
                                   "ver sus diagramas.")
            return

        panel_height = max(self.PANEL_HEIGHT,
                           (height - 24) // max(len(self._series), 1))
        y = 6
        if self._subtitle:
            painter.setPen(QPen(QColor(theme.MUTED)))
            painter.setFont(self._font(10))
            painter.drawText(QRectF(self.MARGIN_LEFT, 2, width - 80, 16),
                             int(Qt.AlignLeft | Qt.AlignVCenter), self._subtitle)
            y += 14
        for series in self._series:
            self._draw_panel(painter, series,
                             QRectF(0, y, width, panel_height))
            y += panel_height

    def _draw_placeholder(self, painter: QPainter, width: int, height: int,
                          text: str) -> None:
        painter.setPen(QPen(QColor(theme.MUTED)))
        painter.setFont(self._font(11))
        painter.drawText(QRectF(20, 0, max(width - 40, 40), height),
                         int(Qt.AlignCenter), text)

    def _draw_panel(self, painter: QPainter, series: Series,
                    rect: QRectF) -> None:
        plot = QRectF(rect.left() + self.MARGIN_LEFT,
                      rect.top() + self.MARGIN_TOP,
                      max(rect.width() - self.MARGIN_LEFT - self.MARGIN_RIGHT, 10),
                      max(rect.height() - self.MARGIN_TOP - self.MARGIN_BOTTOM, 10))

        painter.setPen(QPen(QColor(theme.LINE)))
        painter.setBrush(QBrush(QColor("#fdfefe")))
        painter.drawRoundedRect(plot.adjusted(-6, -10, 6, 10), 6, 6)

        painter.setPen(QPen(QColor(theme.INK)))
        painter.setFont(self._font(11, bold=True))
        painter.drawText(QRectF(rect.left() + 8, rect.top() + 2,
                                rect.width() - 16, 16),
                         int(Qt.AlignLeft | Qt.AlignVCenter),
                         f"{series.title}  [{series.unit}]")

        if series.empty:
            painter.setPen(QPen(QColor(theme.WARN)))
            painter.setFont(self._font(10))
            painter.drawText(plot, int(Qt.AlignCenter),
                             series.note or "Sin datos para trazar.")
            return

        x_min, x_max = min(series.xs), max(series.xs)
        if x_max - x_min <= 0:
            x_max = x_min + 1.0
        y_min, y_max = min(series.ys), max(series.ys)
        span = max(abs(y_min), abs(y_max)) or 1.0
        y_min, y_max = -span * 1.15, span * 1.15

        def px(value: float) -> float:
            return plot.left() + (value - x_min) / (x_max - x_min) * plot.width()

        def py(value: float) -> float:
            ratio = (value - y_min) / (y_max - y_min)
            if series.positive_down:
                return plot.top() + ratio * plot.height()
            return plot.bottom() - ratio * plot.height()

        zero_y = py(0.0)

        # Retícula vertical en cinco divisiones.
        painter.setPen(QPen(QColor(theme.DIAGRAM_GRID), 1, Qt.DashLine))
        for step in range(1, 5):
            x = plot.left() + plot.width() * step / 5.0
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        # Curva rellena hasta el eje cero.
        path = QPainterPath(QPointF(px(series.xs[0]), zero_y))
        for x, value in zip(series.xs, series.ys):
            path.lineTo(QPointF(px(x), py(value)))
        path.lineTo(QPointF(px(series.xs[-1]), zero_y))
        path.closeSubpath()
        color = QColor(series.color)
        fill = QColor(color)
        fill.setAlpha(38)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(color, 1.7))
        painter.drawPath(path)

        # Eje cero.
        painter.setPen(QPen(QColor(theme.DIAGRAM_AXIS), 1.3))
        painter.drawLine(QPointF(plot.left(), zero_y), QPointF(plot.right(), zero_y))

        self._draw_extremes(painter, series, plot, px, py)
        self._draw_scale(painter, series, plot, x_min, x_max, y_min, y_max)

    def _draw_extremes(self, painter: QPainter, series: Series, plot: QRectF,
                       px, py) -> None:
        """Marca y rotula el máximo y el mínimo de la curva."""
        pairs: List[Tuple[str, int]] = []
        top = max(range(len(series.ys)), key=lambda i: series.ys[i])
        bottom = min(range(len(series.ys)), key=lambda i: series.ys[i])
        pairs.append(("max", top))
        if bottom != top:
            pairs.append(("min", bottom))

        painter.setFont(self._font(10, bold=True))
        metrics = QFontMetrics(painter.font())
        scale = max(abs(v) for v in series.ys) or 1.0
        for _, index in pairs:
            x, value = series.xs[index], series.ys[index]
            point = QPointF(px(x), py(value))
            painter.setPen(QPen(QColor(series.color), 1))
            painter.setBrush(QBrush(QColor(series.color)))
            painter.drawEllipse(point, 2.6, 2.6)
            text = f"{_fmt(value, scale)} @ {x:,.2f}"
            offset = -6 if point.y() > plot.center().y() else 14
            box_x = min(max(point.x() - metrics.horizontalAdvance(text) / 2,
                            plot.left()),
                        plot.right() - metrics.horizontalAdvance(text))
            painter.setPen(QPen(QColor(series.color)))
            painter.drawText(QRectF(box_x, point.y() + offset - 8,
                                    metrics.horizontalAdvance(text) + 4, 14),
                             int(Qt.AlignLeft | Qt.AlignVCenter), text)

    def _draw_scale(self, painter: QPainter, series: Series, plot: QRectF,
                    x_min: float, x_max: float, y_min: float,
                    y_max: float) -> None:
        painter.setFont(self._font(9))
        painter.setPen(QPen(QColor(theme.MUTED)))
        # Escala vertical. Los decimales se ajustan a la magnitud, porque una
        # deflexión de 0.0016 m no puede mostrarse como «0.00».
        scale = max(abs(y_min), abs(y_max))
        for value in (y_max, 0.0, y_min):
            ratio = (value - y_min) / (y_max - y_min)
            y = (plot.top() + ratio * plot.height() if series.positive_down
                 else plot.bottom() - ratio * plot.height())
            painter.drawText(QRectF(plot.left() - self.MARGIN_LEFT + 4, y - 7,
                                    self.MARGIN_LEFT - 10, 14),
                             int(Qt.AlignRight | Qt.AlignVCenter),
                             _fmt(value, scale))
        # Escala horizontal.
        for fraction in (0.0, 0.5, 1.0):
            value = x_min + (x_max - x_min) * fraction
            x = plot.left() + plot.width() * fraction
            painter.drawText(QRectF(x - 34, plot.bottom() + 8, 68, 14),
                             int(Qt.AlignCenter),
                             f"{value:,.2f} {self._length_unit}")

    @staticmethod
    def _font(size: int, bold: bool = False) -> QFont:
        font = QFont("Segoe UI")
        font.setPixelSize(size + 2)
        font.setBold(bold)
        return font


def _fmt(value: float, scale: float) -> str:
    """Formatea con los decimales que la magnitud de la curva necesita.

    Un momento de 17 t·m se lee bien con dos decimales; una deflexión de
    0.0016 m no, así que los decimales crecen cuando la escala es chica.
    """
    magnitude = abs(scale)
    if magnitude == 0:
        decimals = 2
    elif magnitude >= 100:
        decimals = 1
    elif magnitude >= 1:
        decimals = 2
    elif magnitude >= 0.1:
        decimals = 3
    elif magnitude >= 0.01:
        decimals = 4
    elif magnitude >= 0.001:
        decimals = 5
    else:
        decimals = 6
    return f"{value:,.{decimals}f}"
