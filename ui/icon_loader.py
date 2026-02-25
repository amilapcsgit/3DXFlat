from __future__ import annotations
import os
import base64

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QAbstractButton

from ui.icons.phase3_b64_icons import ICON_IMPORT_3D_SVG_B64, ICON_ORBIT_3D_SVG_B64
from ui.icons.svg_icon import themed_svg_icon, themed_svg_icon_from_text
from ui.theme import tokens


def _resource_paths(name: str) -> tuple[str, ...]:
    # Keep backward compatibility with existing compiled resources_rc aliases.
    return (f":/icons/{name}.svg", f":/icons/svg/{name}.svg")


def load_icon(name: str, size: int = tokens.ICON_SIZE, color: str | None = None) -> QIcon:
    color_value = QColor(color or tokens.TEXT_PRIMARY)

    # If name is a filesystem path, resolve it
    if os.path.exists(name):
        real_name = os.path.realpath(name)
        try:
            icon = themed_svg_icon(real_name, color=color_value, size_px=size, opacity=1.0)
            if not icon.isNull():
                return icon
        except Exception:
            pass
        return QIcon(real_name)

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


def load_icon_base64_svg(svg_b64: str, size: int = tokens.ICON_SIZE, color: str | None = None) -> QIcon:
    color_value = QColor(color or tokens.TEXT_PRIMARY)
    try:
        svg_text = base64.b64decode(str(svg_b64).encode("ascii"), validate=False).decode("utf-8", errors="replace")
    except Exception:
        return QIcon()
    return themed_svg_icon_from_text(svg_text, color=color_value, size_px=size, opacity=1.0)


class IconRegistry:
    _B64_ICONS: dict[str, str] = {
        "orbit": ICON_ORBIT_3D_SVG_B64,
        "import_3d": ICON_IMPORT_3D_SVG_B64,
    }

    @classmethod
    def get_icon(cls, name: str, *, size: int = tokens.ICON_SIZE, color: str | None = None) -> QIcon:
        key = str(name).strip().lower()
        if key in cls._B64_ICONS:
            return load_icon_base64_svg(cls._B64_ICONS[key], size=size, color=color)
        return load_icon(key, size=size, color=color)


def set_button_icon(
    button: QAbstractButton,
    icon_name: str,
    size: int = tokens.ICON_SIZE,
    color: str | None = None,
) -> None:
    icon_color = color
    if icon_color is None and button.objectName() in {"primaryAction", "btnRunFlatten", "RunFlattenButton"}:
        icon_color = tokens.ON_ACCENT
    icon = load_icon(icon_name, size=size, color=icon_color)
    if icon.isNull():
        return
    button.setIcon(icon)
    button.setIconSize(QSize(size, size))


def set_button_icon_base64_svg(
    button: QAbstractButton,
    svg_b64: str,
    size: int = tokens.ICON_SIZE,
    color: str | None = None,
) -> None:
    icon_color = color
    if icon_color is None and button.objectName() in {"primaryAction", "btnRunFlatten", "RunFlattenButton"}:
        icon_color = tokens.ON_ACCENT
    icon = load_icon_base64_svg(svg_b64, size=size, color=icon_color)
    if icon.isNull():
        return
    button.setIcon(icon)
    button.setIconSize(QSize(size, size))
