from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QAbstractButton

from ui.icons.svg_icon import themed_svg_icon
from ui.theme import tokens


def _resource_paths(name: str) -> tuple[str, ...]:
    # Keep backward compatibility with existing compiled resources_rc aliases.
    return (f":/icons/{name}.svg", f":/icons/svg/{name}.svg")


def load_icon(name: str, size: int = tokens.ICON_SIZE, color: str | None = None) -> QIcon:
    color_value = QColor(color or tokens.TEXT_PRIMARY)
    for svg_path in _resource_paths(name):
        try:
            icon = themed_svg_icon(svg_path, color=color_value, size_px=size, opacity=1.0)
            if not icon.isNull():
                return icon
        except Exception:
            pass

        fallback = QIcon(svg_path)
        if not fallback.isNull():
            pix = fallback.pixmap(QSize(size, size))
            return QIcon(pix) if not pix.isNull() else fallback
    return QIcon()


def load_brand_icon(name: str) -> QIcon:
    return QIcon(f":/brand/{name}")


def set_button_icon(
    button: QAbstractButton,
    icon_name: str,
    size: int = tokens.ICON_SIZE,
    color: str | None = None,
) -> None:
    icon_color = color
    if icon_color is None and button.objectName() in {"primaryAction", "btnRunFlatten"}:
        icon_color = tokens.ON_ACCENT
    icon = load_icon(icon_name, size=size, color=icon_color)
    if icon.isNull():
        return
    button.setIcon(icon)
    button.setIconSize(QSize(size, size))
