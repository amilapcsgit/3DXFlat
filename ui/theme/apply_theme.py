from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from ui.theme import tokens


def _get_qss_override() -> str:
    return f"""
/* ui-enhance-v2.md global override (cross-referenced with ui-enhance.md QOpenGLWidget rule) */

/* Core Window & Backgrounds - Enforcing Tokens */
QMainWindow, QDialog {{ background-color: {tokens.BG_MAIN}; color: {tokens.TEXT_PRIMARY}; }}
QWidget {{ font-family: "{tokens.FONT_FAMILY}", Helvetica, Arial, sans-serif; font-size: {tokens.FONT_SIZE_BODY}px; color: {tokens.TEXT_PRIMARY}; }}

/* 3D Viewport Container (from ui-enhance.md sample logic) */
QOpenGLWidget {{
    background-color: #151515;
    border: 1px solid #333333;
}}

/* 2D Panel & Panels */
QFrame#Panel2D, QWidget#Preview2DPanel {{
    background-color: #1D2127;
    border: 1px solid {tokens.BORDER};
    border-radius: {tokens.RADIUS_PANEL}px;
}}

/* Ribbon Tab System ({tokens.TABS_HEIGHT}px Height) */
QTabWidget::pane {{ border-top: 1px solid {tokens.BORDER}; background-color: {tokens.BG_MAIN}; }}
QTabBar::tab {{
    background-color: {tokens.BG_MAIN};
    color: {tokens.TEXT_SECONDARY};
    height: {tokens.TABS_HEIGHT}px;
    padding: 0px 16px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {tokens.TEXT_PRIMARY}; border-bottom: 2px solid {tokens.ACCENT}; }}
QTabBar::tab:hover {{ color: #ffffff; background-color: {tokens.BG_PANEL}; }}

/* Ribbon Buttons (QToolButton - Secondary Actions) */
QToolButton {{
    background-color: {tokens.BG_PANEL};
    color: {tokens.TEXT_PRIMARY};
    border: 1px solid {tokens.BORDER};
    border-radius: {tokens.RADIUS_BUTTON}px;
    padding: 4px 8px;
    margin: 2px;
    min-width: 60px;
}}
QToolButton:hover {{ background-color: {tokens.BG_HOVER}; border-color: {tokens.ACCENT}; }}
QToolButton:pressed, QToolButton:checked {{ background-color: {tokens.BORDER}; border-color: {tokens.ACCENT}; }}

/* Primary Action Button (Flatten) */
QToolButton#btnRunFlatten {{
    background-color: {tokens.ACCENT};
    color: white;
    border: none;
    font-weight: bold;
}}
QToolButton#btnRunFlatten:hover {{ background-color: #17B6F0; }}

/* Status Bar ({tokens.STATUS_BAR_HEIGHT}px) */
QStatusBar {{
    background-color: {tokens.BG_MAIN};
    border-top: 1px solid {tokens.BORDER};
    color: {tokens.TEXT_SECONDARY};
    min-height: {tokens.STATUS_BAR_HEIGHT}px;
}}
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
    return f"{template}\n\n{_get_qss_override()}\n"


def apply_app_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setFont(QFont(tokens.FONT_FAMILY, tokens.FONT_SIZE_BODY))
    app.setPalette(_build_palette())
    app.setStyleSheet(_build_stylesheet())
