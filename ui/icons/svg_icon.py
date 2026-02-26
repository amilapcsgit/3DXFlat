# ui/icons/svg_icon.py
from __future__ import annotations
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QRect
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def _read_text(path: str) -> str:
    # Works for both resource paths (":/icons/...") and filesystem paths
    if path.startswith(":/"):
        # Read from Qt resources using QFile
        from PySide6.QtCore import QFile, QIODevice
        f = QFile(path)
        if not f.open(QIODevice.ReadOnly):
            raise FileNotFoundError(f"Cannot open resource: {path}")
        data = bytes(f.readAll())
        f.close()
        return data.decode("utf-8", errors="replace")
    else:
        # Resolve symbolic links before reading
        real_path = os.path.realpath(path)
        return Path(real_path).read_text(encoding="utf-8", errors="replace")


def _replace_current_color(svg: str, color_hex: str) -> str:
    # Replace *only* the currentColor usage.
    # Covers stroke/fill/currentColor in styles too.
    return (
        svg.replace('stroke="currentColor"', f'stroke="{color_hex}"')
           .replace("stroke:currentColor", f"stroke:{color_hex}")
           .replace('fill="currentColor"', f'fill="{color_hex}"')
           .replace("fill:currentColor", f"fill:{color_hex}")
    )


@lru_cache(maxsize=256)
def _render_svg_text_pixmap(svg_text: str, size_px: int, color_hex: str, opacity_255: int) -> QPixmap:
    svg_text = _replace_current_color(svg_text, color_hex)
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    pm = QPixmap(size_px, size_px)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setOpacity(opacity_255 / 255.0)
    renderer.render(p, QRect(0, 0, size_px, size_px))
    p.end()
    return pm


@lru_cache(maxsize=512)
def _render_svg_pixmap(svg_key: str, size_px: int, color_hex: str, opacity_255: int) -> QPixmap:
    svg_text = _read_text(svg_key)
    svg_text = _replace_current_color(svg_text, color_hex)

    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    pm = QPixmap(size_px, size_px)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setOpacity(opacity_255 / 255.0)
    renderer.render(p, QRect(0, 0, size_px, size_px))
    p.end()
    return pm


def themed_svg_icon(svg_path: str, *,
                    color: QColor,
                    size_px: int = 24,
                    opacity: float = 1.0) -> QIcon:
    color_hex = color.name(QColor.NameFormat.HexRgb)
    opacity_255 = max(0, min(255, int(opacity * 255)))
    pm = _render_svg_pixmap(svg_path, size_px, color_hex, opacity_255)
    return QIcon(pm)


def themed_svg_icon_from_text(svg_text: str, *,
                              color: QColor,
                              size_px: int = 24,
                              opacity: float = 1.0) -> QIcon:
    color_hex = color.name(QColor.NameFormat.HexRgb)
    opacity_255 = max(0, min(255, int(opacity * 255)))
    pm = _render_svg_text_pixmap(svg_text, size_px, color_hex, opacity_255)
    return QIcon(pm)


def apply_icon(button_or_action, svg_path: str, *,
               color: QColor,
               size_px: int = 24,
               opacity: float = 1.0):
    icon = themed_svg_icon(svg_path, color=color, size_px=size_px, opacity=opacity)
    if hasattr(button_or_action, "setIcon"):
        button_or_action.setIcon(icon)
    if hasattr(button_or_action, "setIconSize"):
        button_or_action.setIconSize(QSize(size_px, size_px))
