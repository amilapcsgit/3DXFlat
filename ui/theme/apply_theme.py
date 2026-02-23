from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from ui.theme import tokens


_UI_ENHANCE_V2_QSS_OVERRIDE = """
/* ui-enhance-v2.md global override (cross-referenced with ui-enhance.md QOpenGLWidget rule) */

/* Core Window & Backgrounds - Enforcing Tokens */
QMainWindow, QDialog { background-color: #1F2227; color: #E5E9F0; }
QWidget { font-family: "Segoe UI", Helvetica, Arial, sans-serif; font-size: 12px; color: #E5E9F0; }

/* 3D Viewport Container (from ui-enhance.md sample logic) */
QOpenGLWidget {
    background-color: #151515;
    border: 1px solid #333333;
}

/* 2D Panel & Panels */
QFrame#Panel2D, QWidget#Preview2DPanel {
    background-color: #1D2127;
    border: 1px solid #3A4048;
    border-radius: 8px;
}

/* Ribbon Tab System (32px Height) */
QTabWidget::pane { border-top: 1px solid #3A4048; background-color: #1F2227; }
QTabBar::tab {
    background-color: #1F2227;
    color: #9AA4B2;
    height: 32px;
    padding: 0px 24px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: #E5E9F0; border-bottom: 2px solid #00AEEF; }
QTabBar::tab:hover { color: #ffffff; background-color: #2A2F36; }

/* Ribbon Buttons (QToolButton - Secondary Actions) */
QToolButton {
    background-color: #2A2F36;
    color: #E5E9F0;
    border: 1px solid #3A4048;
    border-radius: 6px;
    padding: 6px 12px;
    margin: 4px;
    min-width: 80px;
}
QToolButton:hover { background-color: #323842; border-color: #00AEEF; }
QToolButton:pressed, QToolButton:checked { background-color: #3A4048; border-color: #00AEEF; }

/* Primary Action Button (Flatten) */
QToolButton#btnRunFlatten {
    background-color: #00AEEF;
    color: white;
    border: none;
    font-weight: bold;
}
QToolButton#btnRunFlatten:hover { background-color: #17B6F0; }

/* Status Bar (28px) */
QStatusBar {
    background-color: #1F2227;
    border-top: 1px solid #3A4048;
    color: #9AA4B2;
    min-height: 28px;
}
"""


def _build_palette() -> QPalette:
    pal = QPalette()
    bg_main = QColor(tokens.BG_MAIN)
    bg_panel = QColor(tokens.BG_PANEL)
    text_primary = QColor(tokens.TEXT_PRIMARY)
    text_secondary = QColor(tokens.TEXT_SECONDARY)
    accent = QColor(tokens.ACCENT)

    pal.setColor(QPalette.ColorRole.Window, bg_main)
    pal.setColor(QPalette.ColorRole.WindowText, text_primary)
    pal.setColor(QPalette.ColorRole.Base, bg_panel)
    pal.setColor(QPalette.ColorRole.AlternateBase, bg_main)
    pal.setColor(QPalette.ColorRole.ToolTipBase, bg_panel)
    pal.setColor(QPalette.ColorRole.ToolTipText, text_primary)
    pal.setColor(QPalette.ColorRole.Text, text_primary)
    pal.setColor(QPalette.ColorRole.Button, bg_panel)
    pal.setColor(QPalette.ColorRole.ButtonText, text_primary)
    pal.setColor(QPalette.ColorRole.BrightText, QColor(tokens.ERROR))
    pal.setColor(QPalette.ColorRole.Link, accent)
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens.BG_MAIN))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(tokens.TEXT_DISABLED))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(tokens.TEXT_DISABLED))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, text_secondary)
    return pal


def _build_stylesheet() -> str:
    qss_path = Path(__file__).with_name("industrial_cad.qss")
    template = qss_path.read_text(encoding="utf-8")
    for key, value in tokens.qss_vars().items():
        template = template.replace(f"{{{key}}}", value)
    return f"{template}\n\n{_UI_ENHANCE_V2_QSS_OVERRIDE}\n"


def apply_app_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setFont(QFont(tokens.FONT_FAMILY, tokens.FONT_SIZE_BODY))
    app.setPalette(_build_palette())
    app.setStyleSheet(_build_stylesheet())
