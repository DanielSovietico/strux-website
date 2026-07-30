"""Paleta y hoja de estilo, heredadas del visor original de Strux."""

from __future__ import annotations

# Colores del programa original (encabezado azul marino sobre cuerpo claro).
INK = "#111827"
MUTED = "#7c8aa0"
BODY = "#eef2f7"
PANEL = "#ffffff"
LINE = "#e4e9f1"
NAVY = "#0a1226"
NAVY_2 = "#10213f"
BLUE = "#1976d2"
BLUE_DARK = "#1565c0"
CYAN = "#36b6ff"
GOOD = "#2e7d32"
WARN = "#d97706"
BAD = "#c62828"

# Colores de los diagramas.
DIAGRAM_M = "#1565c0"
DIAGRAM_V = "#00897b"
DIAGRAM_D = "#6a1b9a"
DIAGRAM_GRID = "#dfe6ef"
DIAGRAM_AXIS = "#33415a"

STYLESHEET = f"""
QMainWindow, QWidget {{ background: {BODY}; color: {INK}; }}
QLabel#titleLabel {{ font-size: 18px; font-weight: 700; }}
QLabel#stepLabel {{ color: {MUTED}; font-size: 11px; font-weight: 700;
                    letter-spacing: 1.2px; }}
QLabel#hintLabel {{ color: {MUTED}; font-size: 11px; }}

#header {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
             stop:0 {NAVY}, stop:0.7 {NAVY_2}, stop:1 #0c1834); }}
#header QLabel {{ color: #eaf2fb; background: transparent; font-size: 13px; }}
#header QLabel#brand {{ font-size: 20px; font-weight: 800; color: #ffffff;
                        background: transparent; }}
#header QLabel#sourceChip {{
    background: rgba(10,30,60,0.45); border: 1px solid rgba(94,160,220,0.35);
    border-radius: 7px; padding: 4px 9px; color: #cfe0f5; font-size: 11px; }}

QGroupBox {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px;
             margin-top: 14px; padding: 10px 10px 8px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px;
                    color: {BLUE_DARK}; }}

QPushButton {{ background: {PANEL}; border: 1px solid #ccd6e3; border-radius: 7px;
               padding: 6px 12px; }}
QPushButton:hover {{ border-color: {BLUE}; color: {BLUE_DARK}; }}
QPushButton:disabled {{ color: #9aa7b8; background: #f4f7fb; }}
QPushButton#primary {{ background: {BLUE}; border: none; color: #ffffff;
                       font-weight: 600; padding: 7px 16px; }}
QPushButton#primary:hover {{ background: {BLUE_DARK}; }}
QPushButton#primary:disabled {{ background: #9dbfe2; color: #eef4fb; }}

QTableView {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 6px;
              gridline-color: #eef2f7; selection-background-color: #d6e8fb;
              selection-color: {INK}; }}
QHeaderView::section {{ background: #f5f8fc; border: none;
                        border-right: 1px solid {LINE};
                        border-bottom: 1px solid {LINE};
                        padding: 5px 7px; font-weight: 600; color: #33415a; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 8px;
                    background: {PANEL}; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; color: {MUTED};
                font-weight: 600; }}
QTabBar::tab:selected {{ color: {BLUE_DARK};
                         border-bottom: 2px solid {BLUE}; }}
QListWidget, QTreeWidget, QPlainTextEdit, QLineEdit, QComboBox,
QDoubleSpinBox, QSpinBox {{
    background: {PANEL}; border: 1px solid #ccd6e3; border-radius: 6px;
    padding: 3px 6px; }}
QPlainTextEdit {{ font-family: Consolas, "DejaVu Sans Mono", monospace;
                  font-size: 11px; }}
#statusBanner {{ border-radius: 8px; padding: 9px 12px; font-size: 12px; }}
"""


def banner_style(kind: str) -> str:
    """Estilo de los avisos: informativo, advertencia o error."""
    palette = {
        "info": ("#e8f1fb", "#9dc3e6", "#134a7c"),
        "ok": ("#e9f6ec", "#a5d6a7", "#1b5e20"),
        "warn": ("#fff8e6", "#e2b566", "#8a5a00"),
        "error": ("#fdecec", "#e6a1a1", "#8a1c1c"),
    }
    background, border, color = palette.get(kind, palette["info"])
    return (f"background: {background}; border: 1px solid {border}; "
            f"color: {color};")
