from __future__ import annotations

from typing import Tuple

BG_MAIN = "#1F2227"
BG_PANEL = "#2A2F36"
BG_HOVER = "#323842"
BORDER = "#3A4048"
TEXT_PRIMARY = "#E5E9F0"
TEXT_SECONDARY = "#9AA4B2"
TEXT_DISABLED = "#6B7480"
ACCENT = "#00AEEF"
WARN = "#F39C12"
ERROR = "#E74C3C"
SUCCESS = "#2ECC71"

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24

RADIUS_1 = 6
RADIUS_2 = 10

FONT_FAMILY = "Segoe UI Variable"
FONT_FALLBACK = "Segoe UI"
FONT_ALT = "Inter"
FONT_SIZE_RIBBON = 12
FONT_SIZE_BODY = 13
FONT_SIZE_TITLE = 16
FONT_WEIGHT_NORMAL = 400
FONT_WEIGHT_SEMIBOLD = 600


def hex_to_rgbf(value: str) -> Tuple[float, float, float]:
    code = value.strip().lstrip("#")
    if len(code) != 6:
        return (0.0, 0.0, 0.0)
    r = int(code[0:2], 16) / 255.0
    g = int(code[2:4], 16) / 255.0
    b = int(code[4:6], 16) / 255.0
    return (r, g, b)
