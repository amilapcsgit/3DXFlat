from __future__ import annotations

from typing import Dict, Tuple

# Dark UI chrome
BG_MAIN = "#1F2227"
BG_PANEL = "#2A2F36"
BG_HOVER = "#323842"
BORDER = "#3A4048"
TEXT_PRIMARY = "#E5E9F0"
TEXT_SECONDARY = "#9AA4B2"
TEXT_DISABLED = "#6B7480"
ACCENT = "#00AEEF"
ON_ACCENT = "#FFFFFF"
ERROR = "#E74C3C"
WARN = "#F39C12"
SUCCESS = "#2ECC71"

# 3D viewport
VP_BG = "#E6E9ED"
GRID_MINOR = "#D0D5DB"
GRID_MAJOR = "#B7BDC5"
MESH_DIFFUSE = "#7E8896"
EDGE = "#3A4048"
SEL = "#00AEEF"

# 2D preview
P2D_BG = "#1D2127"
P2D_GRID = "#2A2F36"
P2D_OUTER = "#00AEEF"
P2D_INNER = "#E74C3C"

# 8px system
SPACE_XS = 4
SPACE_S = 8
SPACE_M = 16
SPACE_L = 24
SPACE_XL = 32

# Backward-compatible aliases
SPACE_1 = SPACE_XS
SPACE_2 = SPACE_S
SPACE_3 = SPACE_M
SPACE_4 = SPACE_L
SPACE_5 = SPACE_XL

RADIUS_BUTTON = 6
RADIUS_PANEL = 8
RADIUS_FLOATING = 10
RADIUS_1 = RADIUS_BUTTON
RADIUS_2 = RADIUS_FLOATING

# Compact UI Heights (Reduced ~30% for Phase 2 refinement)
PRIMARY_RIBBON_HEIGHT = 44
TABS_HEIGHT = 24
SECONDARY_STRIP_HEIGHT = 34
TOOL_BUTTON_HEIGHT = 24
PANEL_HEADER_HEIGHT = 28
STATUS_BAR_HEIGHT = 22
ICON_SIZE = 18
PANEL_MIN_WIDTH = 420

# Typography
FONT_FAMILY = "Roboto Condensed"
FONT_FALLBACK = "DejaVu Sans"
FONT_SIZE_BUTTON = 11
FONT_SIZE_LABEL = 11
FONT_SIZE_PANEL_TITLE = 12
FONT_SIZE_BODY = 12
FONT_WEIGHT_NORMAL = 400
FONT_WEIGHT_MEDIUM = 500
FONT_WEIGHT_SEMIBOLD = 600


def hex_to_rgb255(value: str) -> Tuple[int, int, int]:
    code = value.strip().lstrip("#")
    if len(code) != 6:
        return (0, 0, 0)
    return (int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16))


def hex_to_rgbf(value: str) -> Tuple[float, float, float]:
    r, g, b = hex_to_rgb255(value)
    return (r / 255.0, g / 255.0, b / 255.0)


def rgba(value: str, alpha: float) -> str:
    r, g, b = hex_to_rgb255(value)
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, alpha)):.3f})"


def qss_vars() -> Dict[str, str]:
    return {
        "BG_MAIN": BG_MAIN,
        "BG_PANEL": BG_PANEL,
        "BG_HOVER": BG_HOVER,
        "BORDER": BORDER,
        "TEXT_PRIMARY": TEXT_PRIMARY,
        "TEXT_SECONDARY": TEXT_SECONDARY,
        "TEXT_DISABLED": TEXT_DISABLED,
        "ACCENT": ACCENT,
        "ON_ACCENT": ON_ACCENT,
        "ERROR": ERROR,
        "P2D_BG": P2D_BG,
        "SPACE_XS": str(SPACE_XS),
        "SPACE_S": str(SPACE_S),
        "SPACE_M": str(SPACE_M),
        "SPACE_L": str(SPACE_L),
        "SPACE_XL": str(SPACE_XL),
        "RADIUS_BUTTON": str(RADIUS_BUTTON),
        "RADIUS_PANEL": str(RADIUS_PANEL),
        "RADIUS_FLOATING": str(RADIUS_FLOATING),
        "PRIMARY_RIBBON_HEIGHT": str(PRIMARY_RIBBON_HEIGHT),
        "TABS_HEIGHT": str(TABS_HEIGHT),
        "SECONDARY_STRIP_HEIGHT": str(SECONDARY_STRIP_HEIGHT),
        "TOOL_BUTTON_HEIGHT": str(TOOL_BUTTON_HEIGHT),
        "PANEL_HEADER_HEIGHT": str(PANEL_HEADER_HEIGHT),
        "STATUS_BAR_HEIGHT": str(STATUS_BAR_HEIGHT),
    }
