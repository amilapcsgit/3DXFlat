from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QProgressBar,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ui.icons.svg_icon import themed_svg_icon
from ui.theme import tokens
from ui.icon_loader import IconRegistry


class UnifiedCommandBar(QWidget):
    ICONS_DIR = Path("ui/icons/Industrial_SVG_Set_v1")

    ICON_MAP: dict[str, str] = {
        "Import Model": "import_model.svg",
        "Reset View": "reset_view.svg",
        "Wireframe": "wireframe.svg",
        "Grid": "grid.svg",
        "Smart Select": "smart_select.svg",
        "Single Pick": "single_pick.svg",
        "Clear": "clear.svg",
        "Invert": "invert.svg",
        "Isolate": "isolate.svg",
        "Show 2D Preview": "toggle_2d_preview.svg",
        "Method": "method_dropdown.svg",
        "Technical": "technical.svg",
        "Edges": "edges.svg",
        "Run Flatten": "run_flatten.svg",
        "Nest": "nest.svg",
        "Export DXF": "export_dxf.svg",
        "Settings": "settings.svg",
        "About": "about.svg",
        "Orbit HUD": "orbit.svg",
        "Pan HUD": "pan.svg",
        "Frame HUD": "frame.svg",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # STRUCTURAL REFACTOR: Two-Row High-DPI Header
        # Adjusted total height to 146px (36 Row1 + 110 Row2) to fix clipping
        self.setFixedHeight(146)
        self.headerArea = QFrame(self)
        self.headerArea.setObjectName("headerArea")
        self.headerArea.setFixedHeight(146)
        self.headerArea.setStyleSheet(f"""
            QFrame#headerArea {{
                border-bottom: 1px solid #3A4048;
                background-color: {tokens.BG_MAIN};
            }}
            #CommandBar QToolButton {{
                color: #E5E9F0 !important;
                max-height: none;
                border: none;
                border-radius: 4px;
            }}
            #CommandBar QToolButton:hover {{
                background-color: {tokens.BG_HOVER};
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.headerArea)

        header_layout = QVBoxLayout(self.headerArea)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        # Row 1 (System Bar): 36px, #1A1D21
        self.row1_widget = QFrame(self.headerArea)
        self.row1_widget.setObjectName("Row1SystemBar")
        self.row1_widget.setFixedHeight(36)
        self.row1_widget.setStyleSheet("background-color: #1A1D21; border: none;")
        self.row1_layout = QHBoxLayout(self.row1_widget)
        self.row1_layout.setContentsMargins(16, 0, 16, 0)
        self.row1_layout.setSpacing(8)

        # Row 2 (Main Command Bar): 110px
        self.row2_widget = QFrame(self.headerArea)
        self.row2_widget.setObjectName("Row2CommandBar")
        self.row2_widget.setFixedHeight(110)
        self.row2_widget.setStyleSheet("background-color: transparent; border: none;")
        self.row2_layout = QHBoxLayout(self.row2_widget)
        self.row2_layout.setContentsMargins(16, 4, 16, 4)
        self.row2_layout.setSpacing(4)

        header_layout.addWidget(self.row1_widget)
        header_layout.addWidget(self.row2_widget)

        self._icon_cache: dict[tuple[str, int, str], QIcon] = {}
        self._build_rows()

    def _load_icon(self, command_name: str, size_px: int, *, color_hex: str | None = None) -> QIcon:
        filename = self.ICON_MAP.get(command_name, "")
        if not filename:
            return QIcon()
        path = (self.ICONS_DIR / filename).resolve()
        if not path.exists():
            return IconRegistry.get_icon(command_name, size=size_px, color=color_hex)

        resolved_color = color_hex or tokens.TEXT_PRIMARY
        cache_key = (str(path), int(size_px), resolved_color)
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]
        icon = themed_svg_icon(str(path), color=QColor(resolved_color), size_px=int(size_px), opacity=1.0)
        self._icon_cache[cache_key] = icon
        return icon

    def _separator(self, parent: QWidget) -> QFrame:
        line = QFrame(parent)
        line.setObjectName("CommandSeparator")
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setLineWidth(1)
        line.setFixedHeight(32)
        line.setStyleSheet(f"background-color: {tokens.BORDER}; border: none;")
        return line

    def _field_shell(self, parent: QWidget, *, title: str, icon_name: str, row: int) -> tuple[QFrame, QHBoxLayout | QVBoxLayout]:
        frame = QFrame(parent)
        frame.setObjectName("Field")

        if row == 1:
            frame.setFixedHeight(26)
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(6, 0, 6, 0)
            layout.setSpacing(4)
        else:
            frame.setFixedHeight(100)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(2)

        frame.setStyleSheet(f"QFrame#Field {{ background-color: #2A2F36; border: 1px solid {tokens.BORDER}; border-radius: 4px; }}")

        title_label = QLabel(title, frame)
        title_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        return frame, layout

    def _button(
        self,
        label: str,
        command_name: str,
        *,
        row: int,
        kind: str = "standard",
        checkable: bool = False,
        object_name: str | None = None,
    ) -> QToolButton | QPushButton:
        if row == 2:
            btn = QToolButton(self)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            font = btn.font()
            font.setPointSize(9)
            font.setWeight(QFont.Weight.DemiBold)
            btn.setFont(font)

            if command_name in ["Run Flatten", "Import Model", "Export DXF"]:
                btn.setFixedSize(110, 100)
                icon_size = 32
            else:
                btn.setFixedWidth(68)
                btn.setFixedHeight(100)
                icon_size = 24

            btn.setIconSize(QSize(icon_size, icon_size))
            btn.setContentsMargins(2, 2, 2, 2)
        else:
            btn = QPushButton(label, self)
            btn.setFixedHeight(28)
            btn.setFixedWidth(68)
            icon_size = 16

        if object_name:
            btn.setObjectName(object_name)
        elif kind == "primary":
            btn.setObjectName("PrimaryButton")
        elif kind == "secondary":
            btn.setObjectName("SecondaryButton")
        elif kind == "toggle":
            btn.setObjectName("ToggleButton")
        else:
            btn.setObjectName("StandardButton")

        btn.setText(label)
        btn.setCheckable(checkable)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        icon_color = tokens.ON_ACCENT if kind == "primary" else tokens.TEXT_PRIMARY
        icon = self._load_icon(command_name, icon_size, color_hex=icon_color)
        if not icon.isNull():
            btn.setIcon(icon)
        return btn

    def _build_rows(self) -> None:
        self._build_row1_general()
        self._build_row2_workflow()
        self._build_hidden_compat_controls()

    def _build_row1_general(self) -> None:
        row = self.row1_layout

        self.btn_settings = self._button("Settings", "Settings", row=1)
        self.btn_about = self._button("About", "About", row=1)

        self.scale_label = QLabel("Scale: -", self.row1_widget)
        self.scale_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
        self.mesh_info_label = QLabel("Mesh: -", self.row1_widget)
        self.mesh_info_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")

        self.quality_gauge = QProgressBar(self.row1_widget)
        self.quality_gauge.setObjectName("QualityGauge")
        self.quality_gauge.setRange(0, 100)
        self.quality_gauge.setValue(0)
        self.quality_gauge.setFormat("Quality: -")
        self.quality_gauge.setFixedWidth(240)
        self.quality_gauge.setFixedHeight(22)
        self.quality_gauge.setToolTip("Weighted mesh quality score based on area error and strain.")
        self.quality_gauge.setStyleSheet(f"""
            QProgressBar {{
                background-color: #2A2F36;
                border: 1px solid {tokens.BORDER};
                border-radius: 4px;
                text-align: center;
                color: white;
                font-size: 10px;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {tokens.ACCENT};
                border-radius: 3px;
            }}
        """)

        units_field, units_row = self._field_shell(self.row1_widget, title="Units", icon_name="Method", row=1)
        self.units_combo = QComboBox(units_field)
        self.units_combo.addItems(["mm", "cm", "m", "inch"])
        self.units_combo.setMinimumWidth(60)
        self.units_combo.setFixedHeight(20)
        self.units_combo.setStyleSheet("background: transparent; border: none;")
        units_row.addWidget(self.units_combo)

        row.addWidget(self.quality_gauge)
        row.addSpacing(8)
        row.addWidget(self._separator(self.row1_widget))
        row.addSpacing(8)
        row.addWidget(units_field)
        row.addWidget(self.scale_label)
        row.addWidget(self.mesh_info_label)
        row.addStretch(1)
        row.addWidget(self.btn_settings)
        row.addWidget(self.btn_about)

    def _build_row2_workflow(self) -> None:
        row = self.row2_layout

        self.btn_import_model = self._button("Import", "Import Model", row=2)
        self.btn_reset_view = self._button("Reset", "Reset View", row=2)
        self.btn_wireframe = self._button("Wire", "Wireframe", row=2, kind="toggle", checkable=True)
        self.btn_grid = self._button("Grid", "Grid", row=2, kind="toggle", checkable=True)
        self.btn_grid.setChecked(True)

        self.btn_smart_select = self._button("Smart", "Smart Select", row=2, kind="toggle", checkable=True)
        self.btn_smart_select.setChecked(True)
        self.btn_single_pick = self._button("Pick", "Single Pick", row=2, kind="toggle", checkable=True)
        self.btn_clear = self._button("Clear", "Clear", row=2)
        self.btn_invert = self._button("Invert", "Invert", row=2)
        self.btn_isolate = self._button("Isolate", "Isolate", row=2, kind="toggle", checkable=True)
        self.btn_toggle_2d = self._button("2D Prev", "Show 2D Preview", row=2, kind="toggle", checkable=True)

        method_field, method_row = self._field_shell(self.row2_widget, title="Method", icon_name="Method", row=2)
        self.method_combo = QComboBox(method_field)
        self.method_combo.addItems(["ARAP", "LSCM"])
        self.method_combo.setMinimumWidth(80)
        self.method_combo.setStyleSheet("background-color: transparent; border: 1px solid #3A4048; border-radius: 4px; padding: 2px;")
        method_row.addWidget(self.method_combo)

        seam_field, seam_row = self._field_shell(self.row2_widget, title="Seam", icon_name="Isolate", row=2)
        self.seam_slider = QSlider(Qt.Orientation.Horizontal, seam_field)
        self.seam_slider.setRange(0, 50)
        self.seam_slider.setValue(12)
        self.seam_slider.setMinimumWidth(80)
        self.seam_label = QLabel("12mm", seam_field)
        self.seam_label.setStyleSheet("font-size: 10px; font-weight: bold;")
        self.seam_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seam_row.addWidget(self.seam_slider)
        seam_row.addWidget(self.seam_label)

        self.btn_technical = self._button("Tech", "Technical", row=2, kind="toggle", checkable=True)
        self.btn_edges = self._button("Edges", "Edges", row=2, kind="toggle", checkable=True)
        self.btn_edges.setChecked(True)

        self.btn_run_flatten = self._button("Flatten", "Run Flatten", row=2, kind="primary")
        self.btn_nest = self._button("Nest", "Nest", row=2)
        self.btn_export_dxf = self._button("Export", "Export DXF", row=2, kind="secondary")

        row.addWidget(self.btn_import_model)
        row.addWidget(self.btn_reset_view)
        row.addWidget(self.btn_wireframe)
        row.addWidget(self.btn_grid)
        row.addWidget(self._separator(self.row2_widget))
        row.addWidget(self.btn_smart_select)
        row.addWidget(self.btn_single_pick)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_invert)
        row.addWidget(self.btn_isolate)
        row.addWidget(self.btn_toggle_2d)
        row.addWidget(self._separator(self.row2_widget))
        row.addWidget(method_field)
        row.addWidget(seam_field)
        row.addWidget(self.btn_technical)
        row.addWidget(self.btn_edges)
        row.addWidget(self._separator(self.row2_widget))
        row.addWidget(self.btn_run_flatten)
        row.addWidget(self.btn_nest)
        row.addWidget(self.btn_export_dxf)
        row.addStretch(1)

        # Force ToolButtonTextUnderIcon style and label visibility
        for i in range(row.count()):
            item = row.itemAt(i)
            if item and (widget := item.widget()) and isinstance(widget, QToolButton):
                widget.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

    def _build_hidden_compat_controls(self) -> None:
        self.selected_label = QLabel("Selected: 0", self)
        self.selected_label.hide()
        self.export_path_label = QLabel("", self)
        self.export_path_label.hide()
