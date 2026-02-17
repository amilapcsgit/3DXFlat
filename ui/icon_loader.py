from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractButton


def load_icon(name: str, size: int | None = None) -> QIcon:
    icon = QIcon()
    svg_path = f":/icons/svg/{name}.svg"
    png24_path = f":/icons/png/{name}_24.png"
    png32_path = f":/icons/png/{name}_32.png"
    # Add SVG first so Qt uses the SVG engine.
    icon.addFile(svg_path)
    icon.addFile(png24_path)
    icon.addFile(png32_path)
    if icon.isNull():
        return QIcon()
    if size is not None:
        pix = icon.pixmap(QSize(size, size))
        if not pix.isNull():
            return QIcon(pix)
    return icon


def load_brand_icon(name: str) -> QIcon:
    return QIcon(f":/brand/{name}")


def set_button_icon(button: QAbstractButton, icon_name: str, size: int = 24) -> None:
    icon = load_icon(icon_name, size=size)
    if icon.isNull():
        return
    button.setIcon(icon)
    button.setIconSize(QSize(size, size))
