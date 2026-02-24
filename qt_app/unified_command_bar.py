from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(152)
        self._icon_cache: dict[tuple[str, int, str], QIcon] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        self._row1 = QHBoxLayout()
        self._row1.setContentsMargins(0, 0, 0, 0)
        self._row1.setSpacing(24)
        root.addLayout(self._row1, 1)

        self._row2 = QHBoxLayout()
        self._row2.setContentsMargins(0, 0, 0, 0)
        self._row2.setSpacing(24)
        root.addLayout(self._row2, 1)

        self._build_groups()

    def _load_icon(self, command_name: str, size_px: int) -> QIcon:
        filename = self.ICON_MAP.get(command_name, "")
        if not filename:
            return QIcon()
        path = (self.ICONS_DIR / filename).resolve()
        if not path.exists():
            return QIcon()
        color_hex = tokens.TEXT_PRIMARY
        cache_key = (str(path), int(size_px), color_hex)
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]
        icon = themed_svg_icon(str(path), color=QColor(color_hex), size_px=int(size_px), opacity=1.0)
        self._icon_cache[cache_key] = icon
        return icon

    def _create_group_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(self)
        card.setObjectName("GroupCard")
        card.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title_lbl = QLabel(title, card)
        title_lbl.setObjectName("GroupTitle")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(title_lbl, 0)
        return card, layout

    def create_ribbon_button(
        self,
        *,
        style_type: str,
        label: str,
        command_name: str,
        checkable: bool = False,
    ) -> QPushButton:
        btn = QPushButton(label, self)
        btn.setCheckable(checkable)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if style_type == "primary":
            btn.setObjectName("PrimaryButton")
            btn.setMinimumSize(172, 48)
            icon_size = 24
        elif style_type == "secondary":
            btn.setObjectName("SecondaryButton")
            btn.setMinimumSize(160, 44)
            icon_size = 22
        elif style_type == "toggle":
            btn.setObjectName("ToggleButton")
            btn.setMinimumSize(132, 40)
            icon_size = 20
        else:
            btn.setObjectName("StandardButton")
            btn.setMinimumSize(132, 40)
            icon_size = 20
        btn.setIconSize(QSize(icon_size, icon_size))
        return btn

    def _button(self, label: str, command_name: str, *, kind: str = "standard", checkable: bool = False) -> QPushButton:
        btn = self.create_ribbon_button(style_type=kind, label=label, command_name=command_name, checkable=checkable)
        icon_size = 24 if kind == "primary" else 22 if kind == "secondary" else 20
        icon = self._load_icon(command_name, icon_size if command_name != "Orbit HUD" else 32)
        if not icon.isNull():
            btn.setIcon(icon)
            btn.setIconSize(QSize(icon_size, icon_size if command_name != "Orbit HUD" else 32))
        # Enforce icon+label presentation (non-negotiable)
        btn.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        return btn

    def _field_container(self, title: str, icon_name: str) -> tuple[QFrame, QHBoxLayout]:
        frame = QFrame(self)
        frame.setObjectName("Field")
        frame.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 4, 10, 4)
        row.setSpacing(8)

        icon_label = QLabel(frame)
        icon = self._load_icon(icon_name, 20)
        if not icon.isNull():
            icon_label.setPixmap(icon.pixmap(20, 20))
        icon_label.setFixedSize(20, 20)
        row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        text_label = QLabel(title, frame)
        text_label.setObjectName("FieldLabel")
        row.addWidget(text_label, 0, Qt.AlignmentFlag.AlignVCenter)
        return frame, row

    def _build_groups(self) -> None:
        # Preload orbit icon at 32px to satisfy the spec requirement (32x32 viewBox handling).
        self._load_icon("Orbit HUD", 32)

        self._build_view_group()
        self._build_select_group()
        self._build_flatten_group()
        self._build_output_group()

    def _build_view_group(self) -> None:
        card, layout = self._create_group_card("VIEW")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.btn_import_model = self._button("Import Model", "Import Model", kind="standard")
        self.btn_reset_view = self._button("Reset View", "Reset View")
        self.btn_wireframe = self._button("Wireframe", "Wireframe", kind="toggle", checkable=True)
        self.btn_grid = self._button("Grid", "Grid", kind="toggle", checkable=True)
        self.btn_grid.setChecked(True)

        grid.addWidget(self.btn_import_model, 0, 0)
        grid.addWidget(self.btn_reset_view, 0, 1)
        grid.addWidget(self.btn_wireframe, 1, 0)
        grid.addWidget(self.btn_grid, 1, 1)

        # Compatibility field(s) retained for existing window logic.
        units_field, units_row = self._field_container("Units", "Method")
        self.units_combo = QComboBox(units_field)
        self.units_combo.setObjectName("Field")
        self.units_combo.addItems(["mm", "cm", "m", "inch"])
        self.units_combo.setCurrentText("mm")
        self.units_combo.setMinimumWidth(100)
        units_row.addWidget(self.units_combo)

        self.scale_label = QLabel("Scale: -", card)
        self.scale_label.setObjectName("FieldLabel")
        self.mesh_info_label = QLabel("Mesh: -", card)
        self.mesh_info_label.setObjectName("FieldLabel")

        layout.addLayout(grid)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        meta_row.addWidget(units_field)
        meta_row.addWidget(self.scale_label, 1)
        meta_row.addWidget(self.mesh_info_label, 1)
        layout.addLayout(meta_row)
        self._row1.addWidget(card, 0)

    def _build_select_group(self) -> None:
        card, layout = self._create_group_card("SELECT")
        row_a = QHBoxLayout()
        row_a.setContentsMargins(0, 0, 0, 0)
        row_a.setSpacing(8)
        row_b = QHBoxLayout()
        row_b.setContentsMargins(0, 0, 0, 0)
        row_b.setSpacing(8)

        self.btn_smart_select = self._button("Smart Select", "Smart Select", kind="toggle", checkable=True)
        self.btn_smart_select.setChecked(True)
        self.btn_single_pick = self._button("Single Pick", "Single Pick", kind="toggle", checkable=True)
        self.btn_clear = self._button("Clear", "Clear")
        self.btn_invert = self._button("Invert", "Invert")
        self.btn_isolate = self._button("Isolate", "Isolate", kind="toggle", checkable=True)
        self.btn_toggle_2d = self._button("Show 2D Preview", "Show 2D Preview", kind="toggle", checkable=True)

        row_a.addWidget(self.btn_smart_select)
        row_a.addWidget(self.btn_single_pick)
        row_a.addWidget(self.btn_clear)
        row_b.addWidget(self.btn_invert)
        row_b.addWidget(self.btn_isolate)
        row_b.addWidget(self.btn_toggle_2d)

        layout.addLayout(row_a)
        layout.addLayout(row_b)
        self._row1.addWidget(card, 1)

    def _build_flatten_group(self) -> None:
        card, layout = self._create_group_card("FLATTEN")
        row_a = QHBoxLayout()
        row_a.setContentsMargins(0, 0, 0, 0)
        row_a.setSpacing(8)
        row_b = QHBoxLayout()
        row_b.setContentsMargins(0, 0, 0, 0)
        row_b.setSpacing(8)

        method_field, method_row = self._field_container("Method", "Method")
        self.method_combo = QComboBox(method_field)
        self.method_combo.setObjectName("Field")
        self.method_combo.addItems(["ARAP", "LSCM"])
        self.method_combo.setCurrentText("ARAP")
        self.method_combo.setMinimumWidth(160)
        method_row.addWidget(self.method_combo)

        self.btn_technical = self._button("Technical", "Technical", kind="toggle", checkable=True)
        self.btn_edges = self._button("Edges", "Edges", kind="toggle", checkable=True)
        self.btn_edges.setChecked(True)
        self.selected_label = QLabel("Selected: 0", card)
        self.selected_label.setObjectName("FieldLabel")

        self.btn_run_flatten = self._button("Run Flatten", "Run Flatten", kind="primary")
        self.quality_gauge = QProgressBar(card)
        self.quality_gauge.setObjectName("Field")
        self.quality_gauge.setRange(0, 100)
        self.quality_gauge.setValue(0)
        self.quality_gauge.setFormat("Quality: -")
        self.quality_gauge.setMaximumWidth(240)

        row_a.addWidget(method_field)
        row_a.addWidget(self.btn_technical)
        row_a.addWidget(self.btn_edges)
        row_a.addWidget(self.selected_label)
        row_a.addStretch(1)

        row_b.addWidget(self.btn_run_flatten)
        row_b.addWidget(self.quality_gauge)
        row_b.addStretch(1)

        layout.addLayout(row_a)
        layout.addLayout(row_b)
        self._row2.addWidget(card, 1)

    def _build_output_group(self) -> None:
        card, layout = self._create_group_card("OUTPUT")
        row_a = QHBoxLayout()
        row_a.setContentsMargins(0, 0, 0, 0)
        row_a.setSpacing(8)
        row_b = QHBoxLayout()
        row_b.setContentsMargins(0, 0, 0, 0)
        row_b.setSpacing(8)

        seam_field, seam_row = self._field_container("Seam", "Method")
        self.seam_slider = QSlider(Qt.Orientation.Horizontal, seam_field)
        self.seam_slider.setObjectName("Field")
        self.seam_slider.setRange(0, 200)
        self.seam_slider.setValue(12)
        self.seam_slider.setMinimumWidth(260)
        seam_row.addWidget(self.seam_slider)

        self.seam_label = QLabel("Seam [12] mm", card)
        self.seam_label.setObjectName("FieldLabel")

        self.btn_nest = self._button("Nest", "Nest")
        self.btn_export_dxf = self._button("Export DXF", "Export DXF", kind="secondary")
        self.btn_settings = self._button("Settings", "Settings")
        self.btn_about = self._button("About", "About")

        self.export_path_label = QLabel("(last path not set)", card)
        self.export_path_label.setObjectName("FieldLabel")
        self.export_path_label.setWordWrap(True)

        row_a.addWidget(seam_field)
        row_a.addWidget(self.seam_label)
        row_a.addStretch(1)

        row_b.addWidget(self.btn_nest)
        row_b.addWidget(self.btn_export_dxf)
        row_b.addWidget(self.btn_settings)
        row_b.addWidget(self.btn_about)

        layout.addLayout(row_a)
        layout.addLayout(row_b)
        layout.addWidget(self.export_path_label)
        self._row2.addWidget(card, 2)
