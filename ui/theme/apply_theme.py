from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QStyleFactory

from ui.theme import tokens


def _build_stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {tokens.BG_MAIN};
        color: {tokens.TEXT_PRIMARY};
        font-size: {tokens.FONT_SIZE_BODY}px;
    }}

    QDockWidget {{
        background-color: {tokens.BG_MAIN};
        color: {tokens.TEXT_PRIMARY};
        border: 1px solid {tokens.BORDER};
    }}

    QMenuBar {{
        background-color: {tokens.BG_MAIN};
        color: {tokens.TEXT_PRIMARY};
        border-bottom: 1px solid {tokens.BORDER};
    }}
    QMenuBar::item {{
        spacing: {tokens.SPACE_2}px;
        padding: {tokens.SPACE_2}px {tokens.SPACE_3}px;
        border-radius: {tokens.RADIUS_1}px;
    }}
    QMenuBar::item:selected {{
        background: {tokens.BG_HOVER};
    }}

    QMenu {{
        background-color: {tokens.BG_PANEL};
        color: {tokens.TEXT_PRIMARY};
        border: 1px solid {tokens.BORDER};
        padding: {tokens.SPACE_1}px;
    }}
    QMenu::item {{
        padding: {tokens.SPACE_2}px {tokens.SPACE_3}px;
        border-radius: {tokens.RADIUS_1}px;
    }}
    QMenu::item:selected {{
        background-color: {tokens.BG_HOVER};
    }}

    QToolBar {{
        background: {tokens.BG_PANEL};
        border: 1px solid {tokens.BORDER};
        spacing: {tokens.SPACE_2}px;
        padding: {tokens.SPACE_1}px;
    }}

    QTabWidget::pane {{
        border: 1px solid {tokens.BORDER};
        background-color: {tokens.BG_MAIN};
    }}
    QTabBar::tab {{
        background: {tokens.BG_PANEL};
        color: {tokens.TEXT_PRIMARY};
        border: 1px solid {tokens.BORDER};
        border-bottom: none;
        border-top-left-radius: {tokens.RADIUS_1}px;
        border-top-right-radius: {tokens.RADIUS_1}px;
        padding: {tokens.SPACE_2}px {tokens.SPACE_4}px;
        min-height: 24px;
    }}
    QTabBar::tab:selected {{
        background: {tokens.BG_HOVER};
        color: {tokens.ACCENT};
    }}

    QPushButton, QToolButton {{
        background-color: {tokens.BG_PANEL};
        color: {tokens.TEXT_PRIMARY};
        border: 1px solid {tokens.BORDER};
        border-radius: {tokens.RADIUS_1}px;
        padding: {tokens.SPACE_2}px {tokens.SPACE_3}px;
    }}
    QPushButton:hover, QToolButton:hover {{
        background-color: {tokens.BG_HOVER};
        border-color: {tokens.ACCENT};
    }}
    QPushButton:pressed, QToolButton:pressed {{
        background-color: {tokens.BG_HOVER};
    }}
    QPushButton:checked, QToolButton:checked {{
        border-color: {tokens.ACCENT};
    }}
    QPushButton:disabled, QToolButton:disabled {{
        color: {tokens.TEXT_DISABLED};
        border-color: {tokens.BORDER};
    }}
    QPushButton#FlattenButton, QToolButton#FlattenButton {{
        border-color: {tokens.ACCENT};
        color: {tokens.ACCENT};
        font-size: {tokens.FONT_SIZE_RIBBON}px;
        font-weight: {tokens.FONT_WEIGHT_SEMIBOLD};
    }}

    QLabel {{
        color: {tokens.TEXT_PRIMARY};
    }}

    QGroupBox {{
        font-weight: {tokens.FONT_WEIGHT_SEMIBOLD};
        border: 1px solid {tokens.BORDER};
        border-radius: {tokens.RADIUS_1}px;
        margin-top: {tokens.SPACE_3}px;
        padding-top: {tokens.SPACE_3}px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: {tokens.SPACE_2}px;
        color: {tokens.TEXT_SECONDARY};
        padding: 0 {tokens.SPACE_1}px;
    }}

    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QListWidget {{
        background: {tokens.BG_PANEL};
        color: {tokens.TEXT_PRIMARY};
        border: 1px solid {tokens.BORDER};
        border-radius: {tokens.RADIUS_1}px;
        padding: {tokens.SPACE_2}px;
    }}
    QComboBox QAbstractItemView {{
        background: {tokens.BG_PANEL};
        color: {tokens.TEXT_PRIMARY};
        border: 1px solid {tokens.BORDER};
        selection-background-color: {tokens.BG_HOVER};
        selection-color: {tokens.TEXT_PRIMARY};
    }}

    QCheckBox, QRadioButton {{
        color: {tokens.TEXT_PRIMARY};
        spacing: {tokens.SPACE_2}px;
    }}

    QStatusBar {{
        background-color: {tokens.BG_PANEL};
        color: {tokens.TEXT_SECONDARY};
        border-top: 1px solid {tokens.BORDER};
    }}
    QStatusBar QLabel {{
        color: {tokens.TEXT_SECONDARY};
        background: transparent;
    }}

    QProgressBar {{
        border: 1px solid {tokens.BORDER};
        border-radius: {tokens.RADIUS_1}px;
        background: {tokens.BG_PANEL};
        color: {tokens.TEXT_PRIMARY};
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {tokens.ACCENT};
        border-radius: {tokens.RADIUS_1}px;
    }}
    """


def apply_app_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setFont(QFont(tokens.FONT_FAMILY, tokens.FONT_SIZE_BODY))
    app.setStyleSheet(_build_stylesheet())
