from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ui.icons.svg_icon import themed_svg_icon
from ui.theme import tokens


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
        # PH2-S1: force the command bar to paint as an opaque block in the normal layout flow.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Focused visual polish: give the two internal 40px lines a small breathing margin.
        self.setMinimumHeight(96)
        self.setMaximumHeight(96)
        self.setFixedHeight(96)
        self._icon_cache: dict[tuple[str, int, str], QIcon] = {}

        root = QVBoxLayout(self)
        # 40 + 8 + 40 + (4 + 4) = 96 total. This removes the cramped/clipped look.
        root.setContentsMargins(12, 4, 12, 4)
        root.setSpacing(8)

        self.row1_widget = QFrame(self)
        self.row1_widget.setObjectName("Row1General")
        self.row1_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.row1_widget.setFixedHeight(40)
        self.row1_layout = QHBoxLayout(self.row1_widget)
        self.row1_layout.setContentsMargins(0, 0, 0, 0)
        self.row1_layout.setSpacing(8)
        root.addWidget(self.row1_widget, 0)

        self.row2_widget = QFrame(self)
        self.row2_widget.setObjectName("Row2Workflow")
        self.row2_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.row2_widget.setFixedHeight(40)
        self.row2_layout = QHBoxLayout(self.row2_widget)
        self.row2_layout.setContentsMargins(0, 0, 0, 0)
        self.row2_layout.setSpacing(8)
        root.addWidget(self.row2_widget, 0)

        self._build_rows()

    def _load_icon(self, command_name: str, size_px: int, *, color_hex: str | None = None) -> QIcon:
        filename = self.ICON_MAP.get(command_name, "")
        if not filename:
            return QIcon()
        path = (self.ICONS_DIR / filename).resolve()
        if not path.exists():
            return QIcon()
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
        line.setMidLineWidth(0)
        line.setFixedHeight(24)
        line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return line

    def _field_shell(self, parent: QWidget, *, title: str, icon_name: str, row: int) -> tuple[QFrame, QHBoxLayout]:
        frame = QFrame(parent)
        frame.setObjectName("Field")
        frame.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        frame.setFixedHeight(32)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        icon_label = QLabel(frame)
        icon_size = 20 if row == 1 else 22
        icon = self._load_icon(icon_name, icon_size)
        if not icon.isNull():
            icon_label.setPixmap(icon.pixmap(icon_size, icon_size))
        icon_label.setFixedSize(icon_size, icon_size)
        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        title_label = QLabel(title, frame)
        title_label.setObjectName("FieldLabel")
        layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignVCenter)
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
    ) -> QPushButton:
        btn = QPushButton(label, self)
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

        btn.setCheckable(checkable)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        if row == 1:
            height = 40
            icon_size = 20
            min_width = 112
        else:
            height = 40
            icon_size = 20
            min_width = 108

        if kind == "primary":
            min_width = 156
            icon_size = 24
        elif kind == "secondary":
            min_width = max(min_width, 136)

        btn.setMinimumHeight(height)
        btn.setMaximumHeight(height)
        btn.setFixedHeight(height)
        btn.setMinimumWidth(min_width)
        icon_color = tokens.ON_ACCENT if kind == "primary" else tokens.TEXT_PRIMARY
        icon = self._load_icon(command_name, 32 if command_name == "Orbit HUD" else icon_size, color_hex=icon_color)
        if not icon.isNull():
            btn.setIcon(icon)
            btn.setIconSize(QSize(icon_size, icon_size))
        return btn

    def _build_rows(self) -> None:
        # Preload the larger 32x32 orbit glyph path to validate rendering of non-24 viewBox icons.
        self._load_icon("Orbit HUD", 32)

        self._build_row1_general()
        self._build_row2_workflow()
        self._build_hidden_compat_controls()

    def _build_row1_general(self) -> None:
        row = self.row1_layout

        self.btn_import_model = self._button("Import 3D", "Import Model", row=1)
        self.btn_reset_view = self._button("Reset View", "Reset View", row=1)
        self.btn_wireframe = self._button("Wireframe", "Wireframe", row=1, kind="toggle", checkable=True)
        self.btn_grid = self._button("Grid", "Grid", row=1, kind="toggle", checkable=True)
        self.btn_grid.setChecked(True)

        units_field, units_row = self._field_shell(self.row1_widget, title="Units", icon_name="Method", row=1)
        self.units_combo = QComboBox(units_field)
        self.units_combo.setObjectName("Field")
        self.units_combo.addItems(["mm", "cm", "m", "inch"])
        self.units_combo.setCurrentText("mm")
        self.units_combo.setMinimumWidth(88)
        self.units_combo.setFixedHeight(32)
        units_row.addWidget(self.units_combo, 0, Qt.AlignmentFlag.AlignVCenter)

        self.scale_label = QLabel("Scale: -", self.row1_widget)
        self.scale_label.setObjectName("FieldLabel")
        self.mesh_info_label = QLabel("Mesh: -", self.row1_widget)
        self.mesh_info_label.setObjectName("FieldLabel")
        self.mesh_info_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        row.addWidget(self.btn_import_model)
        row.addWidget(self.btn_reset_view)
        row.addWidget(self.btn_wireframe)
        row.addWidget(self.btn_grid)
        row.addSpacing(12)
        row.addWidget(self._separator(self.row1_widget), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(12)
        row.addWidget(units_field, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.scale_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.mesh_info_label, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

    def _build_row2_workflow(self) -> None:
        row = self.row2_layout

        self.btn_smart_select = self._button("Smart Select", "Smart Select", row=2, kind="toggle", checkable=True)
        self.btn_smart_select.setChecked(True)
        self.btn_single_pick = self._button("Single Pick", "Single Pick", row=2, kind="toggle", checkable=True)
        self.btn_clear = self._button("Clear", "Clear", row=2)
        self.btn_invert = self._button("Invert", "Invert", row=2)
        self.btn_isolate = self._button("Isolate", "Isolate", row=2, kind="toggle", checkable=True)
        self.btn_toggle_2d = self._button("Show 2D Preview", "Show 2D Preview", row=2, kind="toggle", checkable=True)

        method_field, method_row = self._field_shell(self.row2_widget, title="Method", icon_name="Method", row=2)
        self.method_combo = QComboBox(method_field)
        self.method_combo.setObjectName("Field")
        self.method_combo.addItems(["ARAP", "LSCM"])
        self.method_combo.setCurrentText("ARAP")
        self.method_combo.setMinimumWidth(110)
        self.method_combo.setFixedHeight(32)
        method_row.addWidget(self.method_combo, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_technical = self._button("Technical", "Technical", row=2, kind="toggle", checkable=True)
        self.btn_edges = self._button("Edges", "Edges", row=2, kind="toggle", checkable=True)
        self.btn_edges.setChecked(True)

        self.btn_run_flatten = self._button("Run Flatten", "Run Flatten", row=2, kind="primary")
        self.btn_run_flatten.setObjectName("btnRunFlattenPrimary")
        self.btn_nest = self._button("Nest", "Nest", row=2)
        self.btn_export_dxf = self._button("Export DXF", "Export DXF", row=2, kind="secondary")
        self.btn_export_dxf.setObjectName("btnExportDxfSecondary")

        row.addWidget(self.btn_smart_select)
        row.addWidget(self.btn_single_pick)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_invert)
        row.addWidget(self.btn_isolate)
        row.addWidget(self.btn_toggle_2d)
        row.addSpacing(12)
        row.addWidget(self._separator(self.row2_widget), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(12)
        row.addWidget(method_field, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.btn_technical)
        row.addWidget(self.btn_edges)
        row.addSpacing(12)
        row.addWidget(self._separator(self.row2_widget), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(12)
        row.addWidget(self.btn_run_flatten)
        row.addWidget(self.btn_nest)
        row.addWidget(self.btn_export_dxf)
        row.addStretch(1)

    def _build_hidden_compat_controls(self) -> None:
        # Compatibility widgets retained for existing RibbonMainWindow logic, but not visible in PH2 target layout.
        self.selected_label = QLabel("Selected: 0", self)
        self.selected_label.setObjectName("FieldLabel")
        self.selected_label.hide()

        self.quality_gauge = QProgressBar(self)
        self.quality_gauge.setObjectName("Field")
        self.quality_gauge.setRange(0, 100)
        self.quality_gauge.setValue(0)
        self.quality_gauge.setFormat("Quality: -")
        self.quality_gauge.hide()

        self.seam_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.seam_slider.setObjectName("Field")
        self.seam_slider.setRange(0, 200)
        self.seam_slider.setValue(12)
        self.seam_slider.hide()

        self.seam_label = QLabel("Seam [12] mm", self)
        self.seam_label.setObjectName("FieldLabel")
        self.seam_label.hide()

        self.export_path_label = QLabel("(last path not set)", self)
        self.export_path_label.setObjectName("FieldLabel")
        self.export_path_label.hide()
