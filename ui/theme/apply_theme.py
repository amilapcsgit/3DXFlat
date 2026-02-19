from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from ui.theme import tokens


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
    return template


def apply_app_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setFont(QFont(tokens.FONT_FAMILY, tokens.FONT_SIZE_BODY))
    app.setPalette(_build_palette())
    app.setStyleSheet(_build_stylesheet())
