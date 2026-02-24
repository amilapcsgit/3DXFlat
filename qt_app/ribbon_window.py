from __future__ import annotations

import math
from pathlib import Path
import tempfile
import time
from typing import Dict, Iterable, List, Tuple

import ezdxf
import numpy as np
import trimesh
from PySide6.QtCore import QObject, QPoint, QSize, QSettings, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shapely.geometry import MultiPolygon, Polygon

from flatten_surface.flatten_surface import flatten_mesh
from flatten_surface.import_export import get_unit_scale
from nesting import build_nesting_layout, export_nesting_layout
from qt_app.mesh_io import load_mesh_file
from qt_app.viewcube import ViewCubeWidget
from qt_app.viewport import ThreeDViewportWidget
from ui.icon_loader import IconRegistry
from ui.theme import tokens


class Worker(QObject):
    progress = Signal(int)
    status = Signal(str)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(self, task_name: str, payload: Dict):
        super().__init__()
        self.task_name = task_name
        self.payload = payload

    @Slot()
    def run(self) -> None:
        try:
            if self.task_name == "load_model":
                self.result.emit(self._run_load_model())
            elif self.task_name == "flatten":
                self.result.emit(self._run_flatten())
            else:
                raise ValueError(f"Unknown worker task: {self.task_name}")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def _run_load_model(self) -> Dict:
        path = str(self.payload["path"])
        self.status.emit("Loading 3D model...")
        self.progress.emit(5)
        mesh = load_mesh_file(path)
        self.progress.emit(25)
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
        self.progress.emit(45)
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        if len(vertices) == 0 or len(faces) == 0:
            raise ValueError("Model has no valid triangles.")

        preview_faces = faces
        preview_indices = np.arange(len(faces), dtype=np.int64)
        if len(faces) > 120000:
            step = int(math.ceil(len(faces) / 120000.0))
            preview_faces = faces[::step]
            preview_indices = preview_indices[::step]
        self.progress.emit(70)

        vertex_colors = None
        preview_face_colors = None
        try:
            visual = getattr(mesh, "visual", None)
            visual_defined = bool(getattr(visual, "defined", False)) if visual is not None else False
            if visual is not None and visual_defined:
                raw_vc = np.asarray(getattr(visual, "vertex_colors", []))
                if raw_vc.ndim == 2 and raw_vc.shape[0] == len(vertices) and raw_vc.shape[1] in (3, 4):
                    vertex_colors = raw_vc[:, :4]

                raw_fc = np.asarray(getattr(visual, "face_colors", []))
                if raw_fc.ndim == 2 and raw_fc.shape[0] == len(faces) and raw_fc.shape[1] in (3, 4):
                    preview_face_colors = raw_fc[preview_indices, :4]
        except Exception:
            vertex_colors = None
            preview_face_colors = None

        edges_sorted = np.sort(mesh.edges_sorted, axis=1)
        _, edge_use_counts = np.unique(edges_sorted, axis=0, return_counts=True)
        open_edges = int(np.sum(edge_use_counts == 1))
        non_manifold_edges = int(np.sum(edge_use_counts > 2))
        degenerate = int(np.sum(mesh.area_faces <= 1e-12))
        self.progress.emit(100)
        return {
            "path": path,
            "vertices": vertices,
            "faces": faces,
            "preview_faces": preview_faces,
            "vertex_colors": vertex_colors,
            "preview_face_colors": preview_face_colors,
            "mesh_checks": {
                "open_edges": open_edges,
                "non_manifold_edges": non_manifold_edges,
                "degenerate_faces": degenerate,
            },
        }

    def _run_flatten(self) -> Dict:
        self.status.emit("Running flatten solver...")
        self.progress.emit(5)
        self.progress.emit(20)
        vertices = np.asarray(self.payload["vertices"], dtype=np.float64)
        faces = np.asarray(self.payload["faces"], dtype=np.int64)
        if faces.ndim != 2 or faces.shape[1] != 3:
            raise ValueError("Flatten faces must be triangular Nx3 array.")
        if len(faces) == 0:
            raise ValueError("No faces selected for flatten.")

        # Compact selected patch to contiguous vertex indexing. This avoids instability in native solvers
        # when flattening sparse face subsets picked from a much larger source mesh.
        used_vertices = np.unique(faces.reshape(-1))
        if len(used_vertices) < 3:
            raise ValueError("Selected faces do not form a valid patch.")
        remap = {int(v): i for i, v in enumerate(used_vertices.tolist())}
        compact_faces = np.asarray([[remap[int(a)], remap[int(b)], remap[int(c)]] for a, b, c in faces], dtype=np.int64)
        compact_vertices = vertices[used_vertices]

        # Drop degenerate triangles after remap.
        keep_mask = (
            (compact_faces[:, 0] != compact_faces[:, 1])
            & (compact_faces[:, 1] != compact_faces[:, 2])
            & (compact_faces[:, 0] != compact_faces[:, 2])
        )
        compact_faces = compact_faces[keep_mask]
        if len(compact_faces) == 0:
            raise ValueError("All selected faces became degenerate; cannot flatten.")

        # Remove duplicate triangles and keep only the largest connected component.
        compact_faces = self._sanitize_faces(compact_faces)
        self._validate_open_patch_or_raise(compact_faces)

        res = flatten_mesh(
            vertices=compact_vertices,
            faces=compact_faces,
            path_output=self.payload["path_output"],
            show_plot=False,
            input_unit=self.payload["input_unit"],
            method=self.payload["method"],
            boundary_mode="outer_only",
            seam_allowance_mm=self.payload["seam_allowance_mm"],
            align_to_x=False,
            label_text=self.payload["label_text"],
            auto_relief_cut=True,
            relief_threshold_pct=3.0,
        )
        self.progress.emit(95)
        self.progress.emit(100)
        return {
            "path_output": self.payload["path_output"],
            "flatten_result": res,
        }

    @staticmethod
    def _sanitize_faces(faces: np.ndarray) -> np.ndarray:
        if len(faces) == 0:
            return faces
        canonical = np.sort(faces, axis=1)
        _, unique_idx = np.unique(canonical, axis=0, return_index=True)
        faces = faces[np.sort(unique_idx)]
        if len(faces) <= 1:
            return faces

        edge_to_faces: Dict[Tuple[int, int], List[int]] = {}
        for fi, (a, b, c) in enumerate(faces):
            for u, v in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
                e = (u, v) if u < v else (v, u)
                edge_to_faces.setdefault(e, []).append(fi)

        adj = [set() for _ in range(len(faces))]
        for linked in edge_to_faces.values():
            if len(linked) < 2:
                continue
            for i in range(len(linked)):
                for j in range(i + 1, len(linked)):
                    a = linked[i]
                    b = linked[j]
                    adj[a].add(b)
                    adj[b].add(a)

        seen = set()
        components: List[List[int]] = []
        for start in range(len(faces)):
            if start in seen:
                continue
            stack = [start]
            seen.add(start)
            comp: List[int] = []
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for nb in adj[cur]:
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            components.append(comp)

        if len(components) <= 1:
            return faces
        largest = max(components, key=len)
        return faces[np.asarray(sorted(largest), dtype=np.int64)]

    @staticmethod
    def _validate_open_patch_or_raise(faces: np.ndarray) -> None:
        if len(faces) == 0:
            raise ValueError("No valid triangles in selected patch.")
        edges = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
        edges = np.sort(edges, axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        open_edges = int(np.sum(counts == 1))
        non_manifold = int(np.sum(counts > 2))
        if non_manifold > 0:
            raise ValueError(
                f"Selected patch contains non-manifold edges ({non_manifold}). "
                "Use a cleaner surface selection."
            )
        if open_edges == 0:
            raise ValueError(
                "Selected patch is closed (no open boundary). "
                "Pick only the target sheet/surface to flatten."
            )


class CadGraphicsView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QColor(tokens.P2D_BG))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._panning = False
        self._pan_start = None

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = 1.15 if event.angleDelta().y() > 0 else (1.0 / 1.15)
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning and self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class Flatten2DPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Preview2DPanel")
        self._fold_polygon: Polygon | None = None
        self._seam_mm = 12.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame(self)
        header.setObjectName("Preview2DHeader")
        header.setFixedHeight(tokens.PANEL_HEADER_HEIGHT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(tokens.SPACE_M, 0, tokens.SPACE_M, 0)
        header_layout.setSpacing(tokens.SPACE_S)
        title = QLabel("2D Pattern Preview (CAD)", header)
        title.setStyleSheet(
            f"font-size:{tokens.FONT_SIZE_PANEL_TITLE}px; font-weight:{tokens.FONT_WEIGHT_SEMIBOLD}; color:{tokens.TEXT_PRIMARY};"
        )
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        layout.addWidget(header)

        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        layout.addWidget(body, 1)

        self.scene = QGraphicsScene(self)
        self.view = CadGraphicsView(self.scene, body)
        body_layout.addWidget(self.view, 1)

        self.fold_item = QGraphicsPathItem()
        self.fold_item.setPen(QPen(QColor(tokens.P2D_OUTER), 1.2))
        self.scene.addItem(self.fold_item)
        self.cut_item = QGraphicsPathItem()
        self.cut_item.setPen(QPen(QColor(tokens.P2D_INNER), 1.2))
        self.scene.addItem(self.cut_item)

        self.info = QLabel("No flattened shape yet.", body)
        self.info.setStyleSheet(f"color:{tokens.TEXT_SECONDARY};")
        body_layout.addWidget(self.info)

    def _add_ring(self, path: QPainterPath, coords: Iterable[Tuple[float, float]]) -> None:
        pts = list(coords)
        if len(pts) < 2:
            return
        x0, y0 = pts[0]
        path.moveTo(x0, -y0)
        for x, y in pts[1:]:
            path.lineTo(x, -y)
        path.closeSubpath()

    def _polygon_to_path(self, poly: Polygon) -> QPainterPath:
        path = QPainterPath()
        self._add_ring(path, poly.exterior.coords)
        for hole in poly.interiors:
            self._add_ring(path, hole.coords)
        return path

    def set_fold_polygon(self, poly: Polygon | None, fit: bool = True) -> None:
        self._fold_polygon = poly
        self.render_preview(fit=fit)

    def set_seam(self, seam_mm: float) -> None:
        self._seam_mm = max(0.0, float(seam_mm))
        self.render_preview(fit=False)

    def render_preview(self, fit: bool = False) -> None:
        self.fold_item.setPath(QPainterPath())
        self.cut_item.setPath(QPainterPath())
        if self._fold_polygon is None:
            return
        fold_poly = self._fold_polygon
        cut_poly = fold_poly.buffer(self._seam_mm, join_style=2) if self._seam_mm > 0 else fold_poly
        if isinstance(cut_poly, MultiPolygon):
            cut_poly = max(cut_poly.geoms, key=lambda g: g.area)
        if not cut_poly.is_valid:
            cut_poly = cut_poly.buffer(0)
        if isinstance(cut_poly, MultiPolygon):
            cut_poly = max(cut_poly.geoms, key=lambda g: g.area)
        self.fold_item.setPath(self._polygon_to_path(fold_poly))
        self.cut_item.setPath(self._polygon_to_path(cut_poly))
        rect = self.fold_item.path().boundingRect().united(self.cut_item.path().boundingRect())
        pad = 20
        self.scene.setSceneRect(rect.adjusted(-pad, -pad, pad, pad))
        if fit:
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class RibbonMainWindow(QMainWindow):
    SETTINGS_ORG = "3DXFlat"
    SETTINGS_APP = "RibbonWorkspace"
    VIEWPORT_THEME_KEY = "viewport/theme"
    VIEWPORT_THEME_LIGHT = "light"
    VIEWPORT_THEME_DARK = "dark"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("3DXFlat Advanced (Qt)")
        self.setMinimumSize(1100, 700)
        self._settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self._seam_debounce = QTimer(self)
        self._seam_debounce.setSingleShot(True)
        self._seam_debounce.setInterval(120)
        self._seam_debounce.timeout.connect(self._apply_seam_to_preview)

        self.loaded_model_path: str | None = None
        self.loaded_vertices: np.ndarray | None = None
        self.loaded_faces: np.ndarray | None = None
        self.loaded_preview_faces: np.ndarray | None = None
        self.loaded_mesh_checks: Dict | None = None
        self.flatten_completed = False
        self.last_export_path: str = str(self._settings.value("last_export_path", ""))
        self.last_output_dxf: str | None = None
        self.last_flatten_result: Dict | None = None
        self._busy = False
        self._wait_cursor_on = False
        self._worker_thread: QThread | None = None
        self._worker: Worker | None = None
        self._active_task_name = ""
        self._active_task_started = 0.0
        self._active_success_cb = None
        self._active_after_message = ""
        self._preview2d_visible = False
        self._viewport_theme = self._load_viewport_theme_preference()
        self._log_history: List[str] = []

        self._build_ui()
        self._restore_layout()
        self._update_status_metadata()
        self.log("Ribbon UI initialized.")

    def _build_ui(self) -> None:
        self._build_top_toolbar()
        self._build_status_progress()

        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.viewport_splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self.viewport_splitter.setChildrenCollapsible(False)
        self.viewport_splitter.setHandleWidth(4)
        self.viewport_splitter.setContentsMargins(0, 0, 0, 0)
        self.viewport_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.viewport_splitter.setStyleSheet(
            f"""
            QSplitter::handle:horizontal {{
                background-color: {tokens.BORDER};
                margin: 0px;
            }}
            QSplitter::handle:horizontal:hover {{
                background-color: {tokens.ACCENT};
            }}
            """
        )

        self.viewport = ThreeDViewportWidget(self.viewport_splitter)
        self.viewport.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.viewport.set_viewport_theme(self._viewport_theme)
        self.preview2d = Flatten2DPreviewWidget(self.viewport_splitter)
        self.preview2d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview2d.setMinimumWidth(tokens.PANEL_MIN_WIDTH)
        self.viewport_splitter.addWidget(self.viewport)
        self.viewport_splitter.addWidget(self.preview2d)
        self.viewport_splitter.setStretchFactor(0, 10)
        self.viewport_splitter.setStretchFactor(1, 4)

        self.view_cube = ViewCubeWidget(self.viewport)
        self.view_cube.faceClicked.connect(self._on_viewcube_face_clicked)
        self.view_cube.setWindowFlags(self.view_cube.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.view_cube.show()
        self.viewport.cameraChanged.connect(self._on_viewport_camera_changed)
        self.viewport.facesSelected.connect(self._on_faces_selected)
        self.viewport.modelDropped.connect(self.load_model_file)
        self.viewport.flattenRequested.connect(self.run_flatten)
        self.viewport.splitToggleRequested.connect(self.toggle_2d_preview)
        self.viewport.installEventFilter(self)
        self._position_viewcube()
        self._set_2d_preview_visible(False)

        self.ribbon = self._build_ribbon()
        self.ribbon.setObjectName("SecondaryRibbon")
        strip_h = int(getattr(self, "_phase3_ribbon_strip_height", tokens.SECONDARY_STRIP_HEIGHT))
        self.ribbon.setFixedHeight(strip_h + tokens.TABS_HEIGHT)
        root.addWidget(self.ribbon, 0)
        root.addWidget(self.viewport_splitter, 1)
        root.setStretch(0, 0)
        root.setStretch(1, 10)

        self.setCentralWidget(central)
        self._apply_selection_mode()
        self._update_workflow_enablement()

    def _build_top_toolbar(self) -> None:
        tb = QToolBar("Main Actions", self)
        tb.setObjectName("PrimaryRibbon")
        tb.setMovable(False)
        tb.setIconSize(QSize(tokens.ICON_SIZE, tokens.ICON_SIZE))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.setFixedHeight(tokens.PRIMARY_RIBBON_HEIGHT)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        row_h_margin = tokens.SPACE_L
        row_v_margin = tokens.SPACE_S + tokens.SPACE_XS
        control_spacing = tokens.SPACE_S
        group_spacing = tokens.SPACE_L
        tb_layout = tb.layout()
        if tb_layout is not None:
            tb_layout.setContentsMargins(row_h_margin, row_v_margin, row_h_margin, row_v_margin)
            tb_layout.setSpacing(control_spacing)

        def apply_toolbar_icon(button: QToolButton, icon_name: str, *, size: int = tokens.ICON_SIZE, color: str | None = None) -> None:
            icon = IconRegistry.get_icon(icon_name, size=size, color=color)
            if icon.isNull():
                return
            button.setIcon(icon)
            button.setIconSize(QSize(size, size))

        # Phase 3 cleanup: Import / Run Flatten are singleton actions in ribbon tabs only.
        left_center_spacer = QWidget(self)
        left_center_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        left_center_spacer.setMinimumWidth(group_spacing)
        tb.addWidget(left_center_spacer)

        self.toggle_2d_btn = QToolButton(self)
        self.toggle_2d_btn.setText("Show 2D Preview")
        self.toggle_2d_btn.setCheckable(True)
        self.toggle_2d_btn.setToolTip("Show/Hide 2D Pattern Preview")
        self.toggle_2d_btn.toggled.connect(self.toggle_2d_preview)
        apply_toolbar_icon(self.toggle_2d_btn, "isolate")
        tb.addWidget(self.toggle_2d_btn)

        flatten_output_gap = QWidget(self)
        flatten_output_gap.setFixedWidth(group_spacing)
        tb.addWidget(flatten_output_gap)

        self.export_btn_top = QToolButton(self)
        self.export_btn_top.setText("Export DXF")
        self.export_btn_top.setFixedHeight(tokens.TOOL_BUTTON_HEIGHT)
        self.export_btn_top.setMinimumWidth(110)
        self.export_btn_top.setShortcut("Ctrl+E")
        self.export_btn_top.setToolTip("Export production DXF (Ctrl+E)")
        self.export_btn_top.clicked.connect(self.export_dxf)
        apply_toolbar_icon(self.export_btn_top, "export_dxf")
        tb.addWidget(self.export_btn_top)

        center_utility_spacer = QWidget(self)
        center_utility_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        center_utility_spacer.setMinimumWidth(group_spacing)
        tb.addWidget(center_utility_spacer)

        self.settings_btn_top = QToolButton(self)
        self.settings_btn_top.setText("Settings")
        self.settings_btn_top.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.settings_btn_top.setToolTip("Settings")
        self.settings_btn_top.setFixedHeight(tokens.TOOL_BUTTON_HEIGHT)
        self.settings_btn_top.setMinimumWidth(104)
        self.settings_btn_top.clicked.connect(self._show_settings_dialog)
        apply_toolbar_icon(self.settings_btn_top, "settings")
        tb.addWidget(self.settings_btn_top)

        self.about_btn_top = QToolButton(self)
        self.about_btn_top.setText("About")
        self.about_btn_top.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.about_btn_top.setToolTip("About 3DXFlat Advanced")
        self.about_btn_top.setFixedHeight(tokens.TOOL_BUTTON_HEIGHT)
        self.about_btn_top.setMinimumWidth(92)
        self.about_btn_top.clicked.connect(self._show_about_dialog)
        apply_toolbar_icon(self.about_btn_top, "about")
        tb.addWidget(self.about_btn_top)

        help_menu = self.menuBar().addMenu("Help")
        about_action = QAction("About 3DXFlat Advanced", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

        for btn in (self.toggle_2d_btn, self.export_btn_top, self.settings_btn_top, self.about_btn_top):
            btn.setFixedHeight(tokens.TOOL_BUTTON_HEIGHT)
            btn.setIconSize(QSize(tokens.ICON_SIZE, tokens.ICON_SIZE))
            btn.setStyleSheet("padding: 8px 12px;")

    def _build_ribbon(self) -> QTabWidget:
        if hasattr(self, "ribbon") and isinstance(getattr(self, "ribbon"), QTabWidget):
            try:
                self.ribbon.clear()
                self.ribbon.deleteLater()
            except Exception:
                pass

        tabs = QTabWidget(self)
        tabs.setTabPosition(QTabWidget.TabPosition.North)
        tabs.tabBar().setFixedHeight(tokens.TABS_HEIGHT)
        tabs.setDocumentMode(True)

        secondary_h_margin = tokens.SPACE_M
        secondary_v_margin = tokens.SPACE_S
        control_spacing = tokens.SPACE_S
        group_spacing = tokens.SPACE_L
        # The Phase 3 strip was too short for text-under-icon primary buttons.
        # Increase height so labels remain visible and readable.
        strip_height = 108
        self._phase3_ribbon_strip_height = strip_height

        group_box_style = (
            f"QGroupBox {{ background:{tokens.rgba(tokens.BG_PANEL, 0.45)}; "
            f"border:1px solid {tokens.BORDER}; border-radius:{tokens.RADIUS_PANEL}px; margin-top:0px; }}"
        )

        def button_style(*, kind: str, primary: bool = False) -> str:
            if kind == "large":
                if primary:
                    return (
                        f"QToolButton {{ background:{tokens.ACCENT}; color:{tokens.ON_ACCENT}; border:none; "
                        f"border-radius:{tokens.RADIUS_BUTTON}px; padding:6px 10px; min-width:104px; }}"
                        f"QToolButton:hover {{ background:#17B6F0; }}"
                        f"QToolButton:pressed, QToolButton:checked {{ background:#0996CD; }}"
                        f"QToolButton:disabled {{ color:{tokens.rgba(tokens.ON_ACCENT, 0.65)}; background:{tokens.rgba(tokens.ACCENT, 0.45)}; }}"
                    )
                return (
                    f"QToolButton {{ background:{tokens.BG_PANEL}; color:{tokens.TEXT_PRIMARY}; border:1px solid {tokens.BORDER}; "
                    f"border-radius:{tokens.RADIUS_BUTTON}px; padding:6px 10px; min-width:104px; }}"
                    f"QToolButton:hover {{ background:{tokens.BG_HOVER}; border-color:{tokens.BORDER}; }}"
                    f"QToolButton:pressed, QToolButton:checked {{ background:{tokens.BG_HOVER}; border-color:{tokens.BORDER}; }}"
                    f"QToolButton:disabled {{ color:{tokens.TEXT_DISABLED}; border-color:{tokens.BORDER}; }}"
                )
            return (
                f"QToolButton {{ background:{tokens.BG_PANEL}; color:{tokens.TEXT_PRIMARY}; border:1px solid {tokens.BORDER}; "
                f"border-radius:{tokens.RADIUS_1}px; padding:0px 10px; min-height:{tokens.TOOL_BUTTON_HEIGHT}px; }}"
                f"QToolButton:hover {{ background:{tokens.BG_HOVER}; border-color:{tokens.BORDER}; }}"
                f"QToolButton:pressed, QToolButton:checked {{ background:{tokens.rgba(tokens.BG_HOVER, 0.95)}; border-color:{tokens.BORDER}; }}"
                f"QToolButton:disabled {{ color:{tokens.TEXT_DISABLED}; border-color:{tokens.BORDER}; }}"
            )

        def create_ribbon_button(
            parent: QWidget,
            *,
            type: str,
            text: str,
            tooltip: str | None = None,
            icon_name: str | None = None,
            icon_key: str | None = None,
            icon_size: int | None = None,
            primary: bool = False,
            checkable: bool = False,
            object_name: str | None = None,
        ) -> QToolButton:
            btn = QToolButton(parent)
            if object_name:
                btn.setObjectName(object_name)
            btn.setCheckable(checkable)
            if type == "large":
                btn.setText(text)
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                btn.setMinimumSize(108, 64)
                btn.setMaximumHeight(68)
                size_px = int(icon_size or 22)
                btn.setIconSize(QSize(size_px, size_px))
            else:
                btn.setText(text)
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                btn.setFixedHeight(tokens.TOOL_BUTTON_HEIGHT)
                btn.setMinimumWidth(max(72, len(text) * 7 + 26))
                size_px = int(icon_size or 16)
                btn.setIconSize(QSize(size_px, size_px))
            btn.setToolTip(tooltip or text)
            btn.setStyleSheet(button_style(kind=type, primary=primary))
            if icon_key:
                icon_color = tokens.ON_ACCENT if primary else tokens.TEXT_PRIMARY
                icon = IconRegistry.get_icon(icon_key, size=size_px, color=icon_color)
                if not icon.isNull():
                    btn.setIcon(icon)
            elif icon_name:
                icon_color = tokens.ON_ACCENT if primary else tokens.TEXT_PRIMARY
                icon = IconRegistry.get_icon(icon_name, size=size_px, color=icon_color)
                if not icon.isNull():
                    btn.setIcon(icon)
            return btn

        # SETUP TAB
        setup_tab = QWidget(tabs)
        setup_tab.setFixedHeight(strip_height)
        setup_root = QVBoxLayout(setup_tab)
        setup_root.setContentsMargins(secondary_h_margin, secondary_v_margin, secondary_h_margin, secondary_v_margin)
        setup_root.setSpacing(0)
        setup_row = QHBoxLayout()
        setup_row.setContentsMargins(0, 0, 0, 0)
        setup_row.setSpacing(control_spacing)

        setup_group = QGroupBox(setup_tab)
        setup_group.setTitle("")
        setup_group.setStyleSheet(group_box_style)
        setup_group_layout = QHBoxLayout(setup_group)
        setup_group_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        setup_group_layout.setSpacing(tokens.SPACE_S)

        self.import_btn_setup = create_ribbon_button(
            setup_group,
            type="large",
            text="Import 3D",
            tooltip="Import 3D model (Ctrl+O)",
            icon_key="import_3d",
            icon_size=22,
        )
        self.import_btn_setup.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.import_btn_setup.setText("Import 3D")
        self.import_btn_setup.setShortcut("Ctrl+O")
        self.import_btn_setup.clicked.connect(self.import_3d_dialog)
        setup_group_layout.addWidget(self.import_btn_setup, 0, Qt.AlignmentFlag.AlignTop)

        setup_tools_group = QGroupBox(setup_group)
        setup_tools_group.setTitle("")
        setup_tools_group.setStyleSheet(group_box_style)
        setup_tools_layout = QHBoxLayout(setup_tools_group)
        setup_tools_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        setup_tools_layout.setSpacing(tokens.SPACE_XS)

        self.reset_camera_btn = create_ribbon_button(
            setup_tools_group,
            type="small",
            text="Reset Camera",
            tooltip="Reset camera",
            icon_name="frame_selection",
            icon_size=16,
        )
        self.reset_camera_btn.clicked.connect(self.viewport.reset_camera)

        self.wireframe_btn = create_ribbon_button(
            setup_tools_group,
            type="small",
            text="Wireframe",
            tooltip="Wireframe view",
            icon_name="wireframe",
            icon_size=16,
            checkable=True,
        )
        self.wireframe_btn.toggled.connect(self.viewport.set_wireframe_mode)

        self.grid_btn = create_ribbon_button(
            setup_tools_group,
            type="small",
            text="Grid",
            tooltip="Toggle grid",
            icon_name="show_edges",
            icon_size=16,
            checkable=True,
        )
        self.grid_btn.setChecked(True)
        self.grid_btn.toggled.connect(self.viewport.set_grid_visible)

        setup_tools_layout.addWidget(self.reset_camera_btn)
        setup_tools_layout.addWidget(self.wireframe_btn)
        setup_tools_layout.addWidget(self.grid_btn)
        setup_group_layout.addWidget(setup_tools_group, 0, Qt.AlignmentFlag.AlignTop)

        setup_row.addWidget(setup_group, 0, Qt.AlignmentFlag.AlignTop)
        setup_row.addSpacing(group_spacing)

        self.units_combo = QComboBox(setup_tab)
        self.units_combo.addItems(["mm", "cm", "m", "inch"])
        self.units_combo.setCurrentText("mm")
        self.units_combo.currentTextChanged.connect(self._update_dimension_label_only)
        units_label = QLabel("Units", setup_tab)
        self.scale_label = QLabel("Scale: -", setup_tab)
        self.mesh_info_label = QLabel("Mesh: -", setup_tab)

        setup_meta_group = QGroupBox(setup_tab)
        setup_meta_group.setTitle("")
        setup_meta_group.setStyleSheet(group_box_style)
        setup_meta_layout = QHBoxLayout(setup_meta_group)
        setup_meta_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        setup_meta_layout.setSpacing(tokens.SPACE_S)
        setup_meta_layout.addWidget(units_label)
        setup_meta_layout.addWidget(self.units_combo)
        setup_meta_layout.addSpacing(tokens.SPACE_S)
        setup_meta_layout.addWidget(self.scale_label)
        setup_meta_layout.addWidget(self.mesh_info_label, 1)
        setup_row.addWidget(setup_meta_group, 1, Qt.AlignmentFlag.AlignVCenter)

        setup_root.addLayout(setup_row, 1)
        tabs.addTab(setup_tab, "SETUP")

        # FLATTEN TAB
        flatten_tab = QWidget(tabs)
        flatten_tab.setFixedHeight(strip_height)
        flatten_root = QVBoxLayout(flatten_tab)
        flatten_root.setContentsMargins(secondary_h_margin, secondary_v_margin, secondary_h_margin, secondary_v_margin)
        flatten_root.setSpacing(0)
        flatten_row = QHBoxLayout()
        flatten_row.setContentsMargins(0, 0, 0, 0)
        flatten_row.setSpacing(control_spacing)

        selection_group = QGroupBox(flatten_tab)
        selection_group.setTitle("")
        selection_group.setStyleSheet(group_box_style)
        selection_layout = QHBoxLayout(selection_group)
        selection_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        selection_layout.setSpacing(tokens.SPACE_XS)

        self.smart_select_btn = create_ribbon_button(
            selection_group, type="small", text="Smart Select", tooltip="Smart face selection",
            icon_name="surface_select", icon_size=16, checkable=True
        )
        self.smart_select_btn.setChecked(True)
        self.single_pick_btn = create_ribbon_button(
            selection_group, type="small", text="Single Pick", tooltip="Single face pick",
            icon_name="pin_vertex", icon_size=16, checkable=True
        )
        self.clear_selection_btn = create_ribbon_button(
            selection_group, type="small", text="Clear", tooltip="Clear selected faces",
            icon_name="clear_selection", icon_size=16
        )
        self.invert_selection_btn = create_ribbon_button(
            selection_group, type="small", text="Invert", tooltip="Invert selection",
            icon_name="invert_selection", icon_size=16
        )
        self.isolate_btn = create_ribbon_button(
            selection_group, type="small", text="Isolate", tooltip="Isolate selected region",
            icon_name="isolate", icon_size=16, checkable=True
        )
        self.clear_selection_btn.clicked.connect(self.viewport.clear_selection)
        self.invert_selection_btn.clicked.connect(self.viewport.invert_selection)
        self.isolate_btn.toggled.connect(self._on_isolate_toggled)

        self.selection_mode_group = QButtonGroup(self)
        self.selection_mode_group.setExclusive(True)
        self.selection_mode_group.addButton(self.smart_select_btn)
        self.selection_mode_group.addButton(self.single_pick_btn)
        self.smart_select_btn.clicked.connect(self._apply_selection_mode)
        self.single_pick_btn.clicked.connect(self._apply_selection_mode)

        selection_layout.addWidget(self.smart_select_btn)
        selection_layout.addWidget(self.single_pick_btn)
        selection_layout.addWidget(self.clear_selection_btn)
        selection_layout.addWidget(self.invert_selection_btn)
        selection_layout.addWidget(self.isolate_btn)
        flatten_row.addWidget(selection_group, 0, Qt.AlignmentFlag.AlignTop)

        params_group = QGroupBox(flatten_tab)
        params_group.setTitle("")
        params_group.setStyleSheet(group_box_style)
        params_layout = QHBoxLayout(params_group)
        params_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        params_layout.setSpacing(tokens.SPACE_XS)

        self.method_combo = QComboBox(flatten_tab)
        self.method_combo.addItems(["ARAP", "LSCM"])
        self.method_combo.setCurrentText("ARAP")

        self.technical_mode_btn = create_ribbon_button(
            params_group, type="small", text="Technical", tooltip="Technical shading",
            icon_name="strain_map", icon_size=16, checkable=True
        )
        self.technical_mode_btn.toggled.connect(self.viewport.set_technical_mode)

        self.show_edges_btn = create_ribbon_button(
            params_group, type="small", text="Edges", tooltip="Show mesh edges",
            icon_name="show_edges", icon_size=16, checkable=True
        )
        self.show_edges_btn.setChecked(True)
        self.show_edges_btn.toggled.connect(self.viewport.set_edges_visible)

        method_label = QLabel("Method", params_group)
        self.selected_label = QLabel("Selected: 0", params_group)
        params_layout.addWidget(method_label)
        params_layout.addWidget(self.method_combo)
        params_layout.addWidget(self.technical_mode_btn)
        params_layout.addWidget(self.show_edges_btn)
        params_layout.addWidget(self.selected_label)
        flatten_row.addWidget(params_group, 0, Qt.AlignmentFlag.AlignTop)

        action_group = QGroupBox(flatten_tab)
        action_group.setTitle("")
        action_group.setStyleSheet(group_box_style)
        action_layout = QHBoxLayout(action_group)
        action_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        action_layout.setSpacing(tokens.SPACE_S)

        self.run_flatten_btn_tab = create_ribbon_button(
            action_group,
            type="large",
            text="Run Flatten",
            tooltip="Run flatten solver (F5)",
            icon_name="flatten",
            icon_size=22,
            primary=True,
            object_name="btnRunFlatten",
        )
        self.run_flatten_btn_tab.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.run_flatten_btn_tab.setText("Run Flatten")
        self.run_flatten_btn_tab.setObjectName("btnRunFlatten")
        self.run_flatten_btn_tab.setShortcut("F5")
        self.run_flatten_btn_tab.clicked.connect(self.run_flatten)
        action_layout.addWidget(self.run_flatten_btn_tab, 0, Qt.AlignmentFlag.AlignTop)

        self.quality_gauge = QProgressBar(action_group)
        self.quality_gauge.setRange(0, 100)
        self.quality_gauge.setValue(0)
        self.quality_gauge.setFormat("Quality: -")
        self.quality_gauge.setMaximumWidth(220)
        action_layout.addWidget(self.quality_gauge, 0, Qt.AlignmentFlag.AlignVCenter)
        flatten_row.addWidget(action_group, 0, Qt.AlignmentFlag.AlignTop)
        flatten_row.addStretch(1)

        flatten_root.addLayout(flatten_row, 1)
        tabs.addTab(flatten_tab, "FLATTEN")

        # PRODUCTION TAB
        production_tab = QWidget(tabs)
        production_tab.setFixedHeight(tokens.SECONDARY_STRIP_HEIGHT)
        production_layout = QHBoxLayout(production_tab)
        production_layout.setContentsMargins(secondary_h_margin, secondary_v_margin, secondary_h_margin, secondary_v_margin)
        production_layout.setSpacing(control_spacing)
        self.seam_slider = QSlider(Qt.Orientation.Horizontal, production_tab)
        self.seam_slider.setRange(0, 200)
        self.seam_slider.setValue(12)
        self.seam_label = QLabel("Seam [12] mm", production_tab)
        self.seam_slider.valueChanged.connect(self._on_seam_slider_changed)
        self.nest_btn = QPushButton("Nest", production_tab)
        self.nest_btn.clicked.connect(self.run_nesting_job)
        nest_icon = IconRegistry.get_icon("nest", size=tokens.ICON_SIZE, color=tokens.TEXT_PRIMARY)
        if not nest_icon.isNull():
            self.nest_btn.setIcon(nest_icon)
            self.nest_btn.setIconSize(QSize(tokens.ICON_SIZE, tokens.ICON_SIZE))
        self.export_path_label = QLabel(self.last_export_path or "(last path not set)", production_tab)
        self.export_path_label.setWordWrap(True)
        production_layout.addWidget(self.seam_label)
        production_layout.addWidget(self.seam_slider, 1)
        production_layout.addSpacing(group_spacing)
        production_layout.addWidget(self.nest_btn)
        production_layout.addSpacing(group_spacing)
        production_layout.addWidget(self.export_path_label, 1)
        tabs.addTab(production_tab, "PRODUCTION")

        self.nest_btn.setFixedHeight(tokens.TOOL_BUTTON_HEIGHT)
        self.nest_btn.setIconSize(QSize(tokens.ICON_SIZE, tokens.ICON_SIZE))
        self.nest_btn.setStyleSheet("padding: 8px 12px;")
        for combo in (self.units_combo, self.method_combo):
            combo.setFixedHeight(tokens.TOOL_BUTTON_HEIGHT)

        return tabs

    def _build_status_progress(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        status.setFixedHeight(tokens.STATUS_BAR_HEIGHT)
        self.status_meta_label = QLabel("Units: - | Scale: -", self)
        status.addWidget(self.status_meta_label, 1)
        self.status_diag_label = QLabel("Mesh: -", self)
        status.addPermanentWidget(self.status_diag_label)
        self.status_progress = QProgressBar(self)
        self.status_progress.setVisible(False)
        self.status_progress.setTextVisible(True)
        self.status_progress.setMaximumWidth(320)
        self.status_progress.setFormat("%p%")
        status.addPermanentWidget(self.status_progress)

    def _set_2d_preview_visible(self, visible: bool) -> None:
        self._preview2d_visible = bool(visible)
        if self._preview2d_visible:
            self.preview2d.show()
            total = max(self.viewport_splitter.width(), 1000)
            left = int(total * 0.65)
            right = max(self.preview2d.minimumWidth(), total - left)
            self.viewport_splitter.setSizes([left, right])
        else:
            self.preview2d.hide()
            self.viewport_splitter.setSizes([1, 0])

        if hasattr(self, "toggle_2d_btn"):
            self.toggle_2d_btn.blockSignals(True)
            self.toggle_2d_btn.setChecked(self._preview2d_visible)
            self.toggle_2d_btn.setText("Hide 2D Preview" if self._preview2d_visible else "Show 2D Preview")
            self.toggle_2d_btn.blockSignals(False)

    def toggle_2d_preview(self, checked: bool | None = None) -> None:
        target = (not self._preview2d_visible) if checked is None else bool(checked)
        self._set_2d_preview_visible(target)

    def eventFilter(self, watched, event) -> bool:
        if watched == self.viewport and event.type() == event.Type.Resize:
            self._position_viewcube()
        return super().eventFilter(watched, event)

    def _position_viewcube(self) -> None:
        margin = tokens.SPACE_M
        local_x = self.viewport.width() - self.view_cube.width() - margin
        local_y = margin
        if self.view_cube.isWindow():
            self.view_cube.move(self.viewport.mapToGlobal(QPoint(local_x, local_y)))
        else:
            self.view_cube.move(local_x, local_y)
        self.view_cube.raise_()

    def _on_viewport_camera_changed(self, elev: float, azim: float) -> None:
        self.view_cube.set_rotation(elev, azim)
        self.view_cube.raise_()

    def _on_viewcube_face_clicked(self, face: str) -> None:
        self.viewport.apply_view_preset(face)
        self.view_cube.raise_()
        self.statusBar().showMessage(f"View: {face.title()}", 1500)

    def _on_faces_selected(self, faces: List[int]) -> None:
        self.selected_label.setText(f"Selected: {len(faces)}")
        self.log(f"INFO | Surface selection updated: {len(faces)} face(s)")
        if hasattr(self, "isolate_btn") and not faces and self.isolate_btn.isChecked():
            self.isolate_btn.blockSignals(True)
            self.isolate_btn.setChecked(False)
            self.isolate_btn.blockSignals(False)

    def _apply_selection_mode(self) -> None:
        if self.smart_select_btn.isChecked():
            self.viewport.set_selection_mode("smart")
        elif self.single_pick_btn.isChecked():
            self.viewport.set_selection_mode("single")
        else:
            self.viewport.set_selection_mode("off")

    def _on_isolate_toggled(self, checked: bool) -> None:
        self.viewport.set_isolate_mode(checked)
        if checked and not self.viewport.is_isolate_mode():
            self.isolate_btn.blockSignals(True)
            self.isolate_btn.setChecked(False)
            self.isolate_btn.blockSignals(False)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = bool(busy)
        if busy:
            if not self._wait_cursor_on:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                self._wait_cursor_on = True
            self.status_progress.setVisible(True)
            self.status_progress.setRange(0, 0)
            self.status_progress.setValue(0)
            self.statusBar().showMessage(message or "Working...")
        else:
            if self._wait_cursor_on:
                QApplication.restoreOverrideCursor()
                self._wait_cursor_on = False
            self.status_progress.setVisible(False)
            self.status_progress.setRange(0, 100)
            self.status_progress.setValue(0)
            if message:
                self.statusBar().showMessage(message, 6000)
        self._refresh_action_states()

    def _update_progress(self, value: int) -> None:
        if not self._busy:
            return
        if self.status_progress.minimum() == 0 and self.status_progress.maximum() == 0 and 0 < value < 100:
            self.status_progress.setRange(0, 100)
        self.status_progress.setValue(max(0, min(100, int(value))))

    def _run_worker_task(self, task_name: str, payload: Dict, success_cb, busy_message: str, after_message: str = "") -> None:
        if self._busy:
            self.log("INFO | Busy: wait for current task to finish.")
            return
        self._active_task_name = task_name
        self._active_task_started = time.perf_counter()
        self._active_success_cb = success_cb
        self._active_after_message = after_message
        self._set_busy(True, busy_message)
        self._worker_thread = QThread(self)
        self._worker = Worker(task_name=task_name, payload=payload)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.status.connect(lambda text: self.statusBar().showMessage(text))
        self._worker.result.connect(self._on_worker_result)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._cleanup_worker_refs)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_worker_result(self, payload: object) -> None:
        if self._active_success_cb is None:
            return
        try:
            self._active_success_cb(payload)
        except Exception as exc:
            self._on_worker_error(str(exc))

    def _on_worker_error(self, message: str) -> None:
        title = "Task Error"
        if self._active_task_name == "load_model":
            title = "Load Error"
        elif self._active_task_name == "flatten":
            title = "Flatten Error"
        QMessageBox.critical(self, title, message)
        self.log(f"ERROR | {title}: {message}")

    def _on_worker_finished(self) -> None:
        task = self._active_task_name
        dt = time.perf_counter() - self._active_task_started if self._active_task_started else 0.0
        self._active_task_name = ""
        self._active_task_started = 0.0
        self._active_success_cb = None
        msg = self._active_after_message or (f"{task} completed in {dt:.2f}s" if task else "")
        self._active_after_message = ""
        self._set_busy(False, msg)

    def _cleanup_worker_refs(self) -> None:
        self._worker = None
        self._worker_thread = None

    def _dims_in_mm(self, vertices: np.ndarray) -> Tuple[float, float, float]:
        scale = get_unit_scale(self.units_combo.currentText())
        ext = (vertices.max(axis=0) - vertices.min(axis=0)) * scale
        return float(ext[0]), float(ext[1]), float(ext[2])

    def _update_dimension_label_only(self) -> None:
        if self.loaded_vertices is None:
            self.scale_label.setText("Scale: -")
            self._update_status_metadata()
            return
        lx, ly, lz = self._dims_in_mm(self.loaded_vertices)
        self.scale_label.setText(f"Scale: {lx:.1f} x {ly:.1f} x {lz:.1f} mm")
        if self.loaded_model_path:
            self.viewport.dim_label.setText(f"{Path(self.loaded_model_path).name} | LxWxH: {lx:.1f} x {ly:.1f} x {lz:.1f} mm")
        self._update_status_metadata()

    def check_scale(self) -> None:
        if self.loaded_vertices is None:
            QMessageBox.information(self, "Check Scale", "Load a model first.")
            return
        lx, ly, lz = self._dims_in_mm(self.loaded_vertices)
        txt = f"LxWxH: {lx:.1f} x {ly:.1f} x {lz:.1f} mm"
        self.scale_label.setText(f"Scale: {txt}")
        self.log(f"INFO | {txt}")

    def _show_about_dialog(self) -> None:
        vendor = "Unavailable"
        renderer = "Unavailable"
        version = "Unavailable"
        try:
            from OpenGL import GL as ogl

            self.viewport.makeCurrent()
            raw_vendor = ogl.glGetString(ogl.GL_VENDOR)
            raw_renderer = ogl.glGetString(ogl.GL_RENDERER)
            raw_version = ogl.glGetString(ogl.GL_VERSION)
            vendor = raw_vendor.decode("utf-8", errors="replace") if raw_vendor else "Unavailable"
            renderer = raw_renderer.decode("utf-8", errors="replace") if raw_renderer else "Unavailable"
            version = raw_version.decode("utf-8", errors="replace") if raw_version else "Unavailable"
        except Exception:
            pass
        finally:
            try:
                self.viewport.doneCurrent()
            except Exception:
                pass

        box = QMessageBox(self)
        box.setWindowTitle("About 3DXFlat Advanced")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            "<b>3DXFlat Advanced</b><br/>"
            "Version: 0.1.0<br/>"
            "Build: UI-2026.02.17<br/>"
            "Tagline: Precision 3D-to-2D Surface Flattening<br/>"
            "<br/>"
            f"OpenGL Vendor: {vendor}<br/>"
            f"OpenGL Renderer: {renderer}<br/>"
            f"OpenGL Version: {version}<br/>"
            "<br/>"
            "Website: https://github.com/amilapcsgit/3DXFlat<br/>"
            "Docs: https://github.com/amilapcsgit/3DXFlat#readme<br/>"
            "License Tier: Advanced (placeholder)"
        )
        box.exec()

    def _load_viewport_theme_preference(self) -> str:
        raw = str(self._settings.value(self.VIEWPORT_THEME_KEY, "")).strip().lower()
        if raw in {self.VIEWPORT_THEME_LIGHT, self.VIEWPORT_THEME_DARK}:
            return raw
        # Keep current behavior for existing users when setting is missing.
        return self.VIEWPORT_THEME_LIGHT

    def _apply_viewport_theme(self, theme: str, persist: bool = False) -> None:
        normalized = str(theme).strip().lower()
        if normalized not in {self.VIEWPORT_THEME_LIGHT, self.VIEWPORT_THEME_DARK}:
            normalized = self.VIEWPORT_THEME_LIGHT
        self._viewport_theme = normalized
        if hasattr(self, "viewport"):
            self.viewport.set_viewport_theme(normalized)
        if persist:
            self._settings.setValue(self.VIEWPORT_THEME_KEY, normalized)

    def _show_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.setModal(True)
        dialog.setMinimumWidth(420)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(tokens.SPACE_M, tokens.SPACE_M, tokens.SPACE_M, tokens.SPACE_M)
        root.setSpacing(tokens.SPACE_M)

        tabs = QTabWidget(dialog)
        appearance_page = QWidget(tabs)
        appearance_layout = QVBoxLayout(appearance_page)
        appearance_layout.setContentsMargins(tokens.SPACE_M, tokens.SPACE_M, tokens.SPACE_M, tokens.SPACE_M)
        appearance_layout.setSpacing(tokens.SPACE_S)

        appearance_group = QGroupBox("Viewport", appearance_page)
        group_layout = QVBoxLayout(appearance_group)
        group_layout.setContentsMargins(tokens.SPACE_M, tokens.SPACE_M, tokens.SPACE_M, tokens.SPACE_M)
        group_layout.setSpacing(tokens.SPACE_S)

        theme_label = QLabel("Viewport Theme", appearance_group)
        light_radio = QRadioButton("Light Industrial", appearance_group)
        dark_radio = QRadioButton("Dark Industrial", appearance_group)
        if self._viewport_theme == self.VIEWPORT_THEME_DARK:
            dark_radio.setChecked(True)
        else:
            light_radio.setChecked(True)

        group_layout.addWidget(theme_label)
        group_layout.addWidget(light_radio)
        group_layout.addWidget(dark_radio)
        appearance_layout.addWidget(appearance_group)
        appearance_layout.addStretch(1)
        tabs.addTab(appearance_page, "Appearance")
        root.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        root.addWidget(buttons)

        original_theme = self._viewport_theme

        def _selected_theme() -> str:
            return self.VIEWPORT_THEME_DARK if dark_radio.isChecked() else self.VIEWPORT_THEME_LIGHT

        def _preview_theme() -> None:
            self._apply_viewport_theme(_selected_theme(), persist=False)

        light_radio.toggled.connect(lambda checked: _preview_theme() if checked else None)
        dark_radio.toggled.connect(lambda checked: _preview_theme() if checked else None)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_viewport_theme(_selected_theme(), persist=True)
            self.statusBar().showMessage("Viewport theme updated.", 3000)
        else:
            self._apply_viewport_theme(original_theme, persist=False)

    def import_3d_dialog(self) -> None:
        if self._busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import 3D Model", "", "3D files (*.stl *.obj *.stp *.step)")
        if path:
            self.load_model_file(path)

    def load_model_file(self, path: str) -> None:
        self._run_worker_task(
            task_name="load_model",
            payload={"path": path},
            success_cb=self._apply_loaded_model,
            busy_message="Importing 3D model...",
        )

    def _apply_loaded_model(self, payload: Dict) -> None:
        path = str(payload["path"])
        vertices = np.asarray(payload["vertices"], dtype=np.float64)
        faces = np.asarray(payload["faces"], dtype=np.int64)
        preview_faces = np.asarray(payload["preview_faces"], dtype=np.int64)
        vertex_colors = payload.get("vertex_colors")
        preview_face_colors = payload.get("preview_face_colors")
        self.loaded_model_path = path
        self.loaded_vertices = vertices
        self.loaded_faces = faces
        self.loaded_preview_faces = preview_faces
        self.loaded_mesh_checks = dict(payload.get("mesh_checks", {}))

        dims = self._dims_in_mm(vertices)
        self.viewport.set_mesh(
            Path(path).name,
            vertices,
            preview_faces,
            dims,
            pick_faces=faces,
            vertex_colors=None if vertex_colors is None else np.asarray(vertex_colors),
            face_colors=None if preview_face_colors is None else np.asarray(preview_face_colors),
        )
        self._position_viewcube()
        self._on_viewport_camera_changed(24.0, -58.0)
        self.scale_label.setText(f"Scale: {dims[0]:.1f} x {dims[1]:.1f} x {dims[2]:.1f} mm")
        checks = self.loaded_mesh_checks or {}
        self.mesh_info_label.setText(
            f"Mesh: non-manifold={checks.get('non_manifold_edges', 0)}, open={checks.get('open_edges', 0)}, deg={checks.get('degenerate_faces', 0)}"
        )

        self.flatten_completed = False
        self.last_output_dxf = None
        self.last_flatten_result = None
        self.quality_gauge.setValue(0)
        self.quality_gauge.setFormat("Quality: -")
        self.preview2d.set_fold_polygon(None, fit=False)
        self.viewport.clear_selection()
        self._update_workflow_enablement()
        self._update_status_metadata()
        self.log(f"INFO | Model loaded: {Path(path).name} ({len(vertices)} verts, {len(faces)} faces)")

    def _flatten_faces_payload(self) -> np.ndarray | None:
        source_faces = self.viewport.pick_faces if self.viewport.pick_faces is not None else self.loaded_faces
        if source_faces is None:
            return None
        selected = self.viewport.get_selected_faces()
        if selected:
            idx = np.asarray(selected, dtype=np.int64)
            if np.any(idx < 0) or np.any(idx >= len(source_faces)):
                return None
            return source_faces[idx]
        return source_faces

    def run_flatten(self) -> None:
        if self._busy:
            return
        if self.loaded_vertices is None or self.loaded_faces is None:
            QMessageBox.information(self, "Flatten", "Load a model first.")
            return
        faces_to_flatten = self._flatten_faces_payload()
        if faces_to_flatten is None or len(faces_to_flatten) == 0:
            QMessageBox.warning(self, "Flatten", "No valid faces selected.")
            return
        tmp = Path(tempfile.gettempdir()) / "3dxflat_qt_preview.dxf"
        method = self.method_combo.currentText() or "ARAP"
        self._run_worker_task(
            task_name="flatten",
            payload={
                "vertices": self.loaded_vertices,
                "faces": faces_to_flatten,
                "path_output": str(tmp),
                "input_unit": self.units_combo.currentText(),
                "method": method,
                "seam_allowance_mm": float(self.seam_slider.value()),
                "label_text": Path(self.loaded_model_path).stem if self.loaded_model_path else "panel",
            },
            success_cb=self._apply_flatten_preview,
            busy_message=f"Flattening with {method}...",
        )

    def _apply_flatten_preview(self, payload: Dict) -> None:
        path_output = str(payload["path_output"])
        res = dict(payload["flatten_result"])
        self.last_output_dxf = path_output
        self.last_flatten_result = res
        fold_poly = self._read_fold_polygon_from_dxf(path_output)
        self.preview2d.set_fold_polygon(fold_poly, fit=True)
        self.preview2d.set_seam(float(self.seam_slider.value()))
        self.flatten_completed = True
        self._update_workflow_enablement()
        self._update_distortion_gauge(res)
        self.log(f"INFO | Flatten complete ({res.get('method', 'ARAP')}).")

    def _run_flatten_to_path(self, path: str) -> None:
        faces_to_flatten = self._flatten_faces_payload()
        if self.loaded_vertices is None or faces_to_flatten is None or len(faces_to_flatten) == 0:
            QMessageBox.warning(self, "Export", "No valid faces selected.")
            return
        method = self.method_combo.currentText() or "ARAP"
        self._run_worker_task(
            task_name="flatten",
            payload={
                "vertices": self.loaded_vertices,
                "faces": faces_to_flatten,
                "path_output": path,
                "input_unit": self.units_combo.currentText(),
                "method": method,
                "seam_allowance_mm": float(self.seam_slider.value()),
                "label_text": Path(self.loaded_model_path).stem if self.loaded_model_path else "panel",
            },
            success_cb=self._apply_export_result,
            busy_message=f"Exporting DXF with {method}...",
            after_message=f"Exported DXF: {Path(path).name}",
        )

    def _apply_export_result(self, payload: Dict) -> None:
        path_output = str(payload["path_output"])
        res = dict(payload["flatten_result"])
        self.last_export_path = path_output
        self._settings.setValue("last_export_path", path_output)
        self.export_path_label.setText(path_output)
        self.last_output_dxf = path_output
        self.last_flatten_result = res
        self.flatten_completed = True
        self._update_workflow_enablement()
        self._update_distortion_gauge(res)

    def export_dxf(self) -> None:
        if self._busy:
            return
        if self.loaded_vertices is None or self.loaded_faces is None:
            QMessageBox.information(self, "Export", "Load a model first.")
            return
        default = self.last_export_path or ""
        path, _ = QFileDialog.getSaveFileName(self, "Export Production DXF", default, "DXF files (*.dxf)")
        if not path:
            return
        self._run_flatten_to_path(path)

    def run_nesting_job(self) -> None:
        try:
            if not self.flatten_completed:
                raise ValueError("Run flatten first.")
            if not self.last_export_path:
                raise ValueError("Export at least one DXF first.")
            folder = str(Path(self.last_export_path).parent)
            layout = build_nesting_layout(
                input_dir=folder,
                roll_width_mm=2500.0,
                gap_mm=20.0,
                rotation_step_deg=15.0,
                max_sheet_length_mm=10000.0,
            )
            files = export_nesting_layout(output_dir=folder, placements_by_sheet=layout["placements_by_sheet"])
            self.log(f"INFO | Nesting done: {len(files)} output sheet(s).")
        except Exception as exc:
            QMessageBox.warning(self, "Nesting", str(exc))
            self.log(f"ERROR | Nesting error: {exc}")

    def _read_fold_polygon_from_dxf(self, path: str) -> Polygon:
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
        polys = []
        for e in msp:
            if e.dxf.layer not in {"FOLD_LINE", "CUT_LINE"}:
                continue
            poly = self._entity_to_polygon(e)
            if poly is not None:
                polys.append(poly)
        if not polys:
            raise ValueError("No FOLD_LINE/CUT_LINE geometry found.")
        return max(polys, key=lambda p: p.area)

    def _entity_to_polygon(self, entity) -> Polygon | None:
        points: List[Tuple[float, float]] = []
        if entity.dxftype() == "LWPOLYLINE":
            points = [(float(p[0]), float(p[1])) for p in entity.get_points()]
            if not entity.closed and points and points[0] != points[-1]:
                points.append(points[0])
        elif entity.dxftype() == "POLYLINE":
            points = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
            if not entity.is_closed and points and points[0] != points[-1]:
                points.append(points[0])
        if len(points) < 3:
            return None
        poly = Polygon(points)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda g: g.area)
        return poly

    def _on_seam_slider_changed(self, value: int) -> None:
        self.seam_label.setText(f"Seam [{value}] mm")
        self._seam_debounce.start()

    def _apply_seam_to_preview(self) -> None:
        self.preview2d.set_seam(float(self.seam_slider.value()))

    def _update_distortion_gauge(self, flatten_result: Dict) -> None:
        metrics = flatten_result.get("metrics", {}) if flatten_result else {}
        area_err = float(metrics.get("area_error_pct", 0.0))
        perim_err = float(metrics.get("perimeter_error_pct", 0.0))
        strain = np.asarray(flatten_result.get("strain_percent_per_face", []), dtype=np.float64)
        mean_strain = float(np.mean(strain)) if strain.size else 0.0
        score = max(0.0, 100.0 - min(100.0, area_err * 2.0 + perim_err * 0.8 + mean_strain * 6.0))
        self.quality_gauge.setValue(int(round(score)))
        self.quality_gauge.setFormat(f"Quality: {score:.0f}% | area {area_err:.2f}% | strain {mean_strain:.2f}%")

    @staticmethod
    def _set_control_state(control: QWidget, enabled: bool, enabled_tip: str, disabled_tip: str) -> None:
        control.setEnabled(bool(enabled))
        control.setToolTip(enabled_tip if enabled else disabled_tip)

    def _refresh_action_states(self) -> None:
        has_model = self.loaded_vertices is not None and self.loaded_faces is not None
        can_interact = not self._busy
        can_flatten = can_interact and has_model
        can_preview = can_interact and has_model
        can_export = can_interact and self.flatten_completed
        can_nest = can_interact and self.flatten_completed
        can_view = can_interact and has_model
        busy_reason = "Wait for the current task to finish."
        need_model_reason = "Import a model first."
        need_flatten_reason = busy_reason if not can_interact else "Run flatten first."
        flatten_reason = busy_reason if not can_interact else need_model_reason
        view_reason = busy_reason if not can_interact else need_model_reason

        if hasattr(self, "import_btn_setup"):
            self._set_control_state(
                self.import_btn_setup,
                can_interact,
                "Import 3D model (Ctrl+O)",
                busy_reason,
            )
        if hasattr(self, "run_flatten_btn_tab"):
            self._set_control_state(
                self.run_flatten_btn_tab,
                can_flatten,
                "Run flatten solver (F5)",
                flatten_reason,
            )
        self._set_control_state(
            self.toggle_2d_btn,
            can_preview,
            "Show/Hide 2D Pattern Preview",
            flatten_reason,
        )
        self._set_control_state(
            self.export_btn_top,
            can_export,
            "Export production DXF (Ctrl+E)",
            need_flatten_reason,
        )
        self._set_control_state(
            self.settings_btn_top,
            can_interact,
            "Settings",
            busy_reason,
        )
        self._set_control_state(
            self.about_btn_top,
            can_interact,
            "About 3DXFlat Advanced",
            busy_reason,
        )

        self._set_control_state(
            self.reset_camera_btn,
            can_view,
            "Reset camera",
            view_reason,
        )
        self._set_control_state(
            self.grid_btn,
            can_view,
            "Toggle grid",
            view_reason,
        )
        self._set_control_state(
            self.wireframe_btn,
            can_view,
            "Wireframe view",
            view_reason,
        )

        self._set_control_state(
            self.smart_select_btn,
            can_flatten,
            "Smart face selection",
            flatten_reason,
        )
        self._set_control_state(
            self.single_pick_btn,
            can_flatten,
            "Single face pick",
            flatten_reason,
        )
        self._set_control_state(
            self.clear_selection_btn,
            can_flatten,
            "Clear selected faces",
            flatten_reason,
        )
        self._set_control_state(
            self.invert_selection_btn,
            can_flatten,
            "Invert selection",
            flatten_reason,
        )
        self._set_control_state(
            self.isolate_btn,
            can_flatten,
            "Isolate selected region",
            flatten_reason,
        )
        self._set_control_state(
            self.technical_mode_btn,
            can_flatten,
            "Technical shading",
            flatten_reason,
        )
        self._set_control_state(
            self.show_edges_btn,
            can_flatten,
            "Show mesh edges",
            flatten_reason,
        )
        self._set_control_state(
            self.nest_btn,
            can_nest,
            "Build nesting layout",
            need_flatten_reason,
        )

    def _update_workflow_enablement(self) -> None:
        self._refresh_action_states()

    def _update_status_metadata(self) -> None:
        unit = self.units_combo.currentText() if hasattr(self, "units_combo") else "-"
        if self.loaded_vertices is None:
            self.status_meta_label.setText(f"Units: {unit} | Scale: -")
            self.status_diag_label.setText("Mesh: -")
            return
        lx, ly, lz = self._dims_in_mm(self.loaded_vertices)
        self.status_meta_label.setText(f"Units: {unit} | LxWxH: {lx:.1f} x {ly:.1f} x {lz:.1f} mm")
        checks = self.loaded_mesh_checks or {}
        self.status_diag_label.setText(
            f"Mesh nM:{checks.get('non_manifold_edges', 0)} open:{checks.get('open_edges', 0)} deg:{checks.get('degenerate_faces', 0)}"
        )

    def log(self, message: str) -> None:
        self._log_history.append(message)
        self.statusBar().showMessage(message, 5000)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(1500)
        if self._wait_cursor_on:
            QApplication.restoreOverrideCursor()
            self._wait_cursor_on = False
        self._save_layout()
        super().closeEvent(event)

    def _save_layout(self) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.remove("state")
        self._settings.setValue("last_export_path", self.last_export_path)

    def _restore_layout(self) -> None:
        geometry = self._settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)


def create_window() -> RibbonMainWindow:
    return RibbonMainWindow()
