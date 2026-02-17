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
    QFileDialog,
    QGroupBox,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
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
from ui.icon_loader import set_button_icon
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
        self.setBackgroundBrush(QColor(tokens.BG_MAIN))
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
        self._fold_polygon: Polygon | None = None
        self._seam_mm = 12.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
        title = QLabel("2D Pattern Preview (CAD)", self)
        title.setStyleSheet(f"font-size:{tokens.FONT_SIZE_RIBBON}px; font-weight:{tokens.FONT_WEIGHT_SEMIBOLD}; color:{tokens.TEXT_PRIMARY};")
        layout.addWidget(title)

        self.scene = QGraphicsScene(self)
        self.view = CadGraphicsView(self.scene, self)
        layout.addWidget(self.view, 1)

        self.fold_item = QGraphicsPathItem()
        self.fold_item.setPen(QPen(QColor(tokens.ACCENT), 1.2))
        self.scene.addItem(self.fold_item)
        self.cut_item = QGraphicsPathItem()
        self.cut_item.setPen(QPen(QColor(tokens.ERROR), 1.2))
        self.scene.addItem(self.cut_item)

        self.info = QLabel("No flattened shape yet.", self)
        self.info.setStyleSheet(f"color:{tokens.TEXT_SECONDARY};")
        layout.addWidget(self.info)

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
        self.viewport_splitter.setHandleWidth(6)
        self.viewport_splitter.setContentsMargins(0, 0, 0, 0)
        self.viewport_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.viewport_splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {tokens.BORDER}; }}")

        self.viewport = ThreeDViewportWidget(self.viewport_splitter)
        self.viewport.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview2d = Flatten2DPreviewWidget(self.viewport_splitter)
        self.preview2d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview2d.setStyleSheet(f"background-color: {tokens.BG_MAIN};")
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
        self.ribbon.setFixedHeight(140)
        root.addWidget(self.ribbon, 0)
        root.addWidget(self.viewport_splitter, 1)
        root.setStretch(0, 0)
        root.setStretch(1, 10)

        self.setCentralWidget(central)
        self._apply_selection_mode()
        self._update_workflow_enablement()

    def _build_top_toolbar(self) -> None:
        tb = QToolBar("Main Actions", self)
        tb.setMovable(False)
        tb.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        self.import_btn = QToolButton(self)
        self.import_btn.setText("Import 3D")
        self.import_btn.clicked.connect(self.import_3d_dialog)
        set_button_icon(self.import_btn, "import_model")
        tb.addWidget(self.import_btn)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self.run_flatten_btn_top = QToolButton(self)
        self.run_flatten_btn_top.setText("Run Flatten")
        self.run_flatten_btn_top.setObjectName("FlattenButton")
        self.run_flatten_btn_top.clicked.connect(self.run_flatten)
        set_button_icon(self.run_flatten_btn_top, "flatten")
        tb.addWidget(self.run_flatten_btn_top)

        spacer2 = QWidget(self)
        spacer2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer2)

        self.export_btn_top = QToolButton(self)
        self.export_btn_top.setText("Export DXF")
        self.export_btn_top.clicked.connect(self.export_dxf)
        set_button_icon(self.export_btn_top, "export_dxf")
        tb.addWidget(self.export_btn_top)

        self.settings_btn_top = QToolButton(self)
        self.settings_btn_top.setText("Settings")
        self.settings_btn_top.clicked.connect(self._show_settings_placeholder)
        set_button_icon(self.settings_btn_top, "settings")
        tb.addWidget(self.settings_btn_top)

        self.about_btn_top = QToolButton(self)
        self.about_btn_top.setText("About")
        self.about_btn_top.clicked.connect(self._show_about_dialog)
        set_button_icon(self.about_btn_top, "about")
        tb.addWidget(self.about_btn_top)

        help_menu = self.menuBar().addMenu("Help")
        about_action = QAction("About 3DXFlat Advanced", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _build_ribbon(self) -> QTabWidget:
        tabs = QTabWidget(self)
        tabs.setTabPosition(QTabWidget.TabPosition.North)

        setup_tab = QWidget(tabs)
        setup_layout = QHBoxLayout(setup_tab)
        setup_layout.setContentsMargins(10, 10, 10, 10)
        setup_layout.setSpacing(10)
        import_group = QGroupBox("Import", setup_tab)
        import_layout = QHBoxLayout(import_group)
        import_layout.setContentsMargins(10, 10, 10, 10)
        import_layout.setSpacing(8)
        self.setup_import_btn = QPushButton("Import Model", setup_tab)
        self.setup_import_btn.clicked.connect(self.import_3d_dialog)
        set_button_icon(self.setup_import_btn, "import_model")
        self.check_scale_btn = QPushButton("Check Scale", setup_tab)
        self.check_scale_btn.clicked.connect(self.check_scale)
        set_button_icon(self.check_scale_btn, "frame_selection")
        self.reset_camera_btn = QPushButton("Reset Camera", setup_tab)
        self.reset_camera_btn.clicked.connect(self.viewport.reset_camera)
        set_button_icon(self.reset_camera_btn, "frame_selection")
        self.toggle_2d_btn = QPushButton("Show 2D Preview", setup_tab)
        self.toggle_2d_btn.setCheckable(True)
        self.toggle_2d_btn.toggled.connect(self.toggle_2d_preview)
        set_button_icon(self.toggle_2d_btn, "surface_select")
        import_layout.addWidget(self.setup_import_btn)
        import_layout.addWidget(self.check_scale_btn)
        import_layout.addWidget(self.reset_camera_btn)
        import_layout.addWidget(self.toggle_2d_btn)

        scale_group = QGroupBox("Scale & Mesh", setup_tab)
        scale_layout = QHBoxLayout(scale_group)
        scale_layout.setContentsMargins(10, 10, 10, 10)
        scale_layout.setSpacing(8)
        self.units_combo = QComboBox(setup_tab)
        self.units_combo.addItems(["mm", "cm", "m", "inch"])
        self.units_combo.setCurrentText("mm")
        self.units_combo.currentTextChanged.connect(self._update_dimension_label_only)
        self.scale_label = QLabel("Scale: -", setup_tab)
        self.mesh_info_label = QLabel("Mesh: -", setup_tab)
        self.mesh_info_label.setWordWrap(True)
        scale_layout.addWidget(QLabel("Input Units:", setup_tab))
        scale_layout.addWidget(self.units_combo)
        scale_layout.addWidget(self.scale_label, 1)
        scale_layout.addWidget(self.mesh_info_label, 1)
        setup_layout.addWidget(import_group, 1)
        setup_layout.addWidget(scale_group, 2)
        tabs.addTab(setup_tab, "SETUP")

        flatten_tab = QWidget(tabs)
        flatten_layout = QHBoxLayout(flatten_tab)
        flatten_layout.setContentsMargins(10, 10, 10, 10)
        flatten_layout.setSpacing(8)
        self.smart_select_btn = QPushButton("Smart Select (Mode)", flatten_tab)
        self.smart_select_btn.setCheckable(True)
        self.smart_select_btn.setChecked(True)
        self.single_pick_btn = QPushButton("Single Pick (Mode)", flatten_tab)
        self.single_pick_btn.setCheckable(True)
        self.clear_selection_btn = QPushButton("Clear Selection", flatten_tab)
        self.clear_selection_btn.clicked.connect(self.viewport.clear_selection)
        self.invert_selection_btn = QPushButton("Invert", flatten_tab)
        self.invert_selection_btn.clicked.connect(self.viewport.invert_selection)
        self.isolate_btn = QPushButton("Isolate", flatten_tab)
        self.isolate_btn.setCheckable(True)
        self.isolate_btn.toggled.connect(self._on_isolate_toggled)
        self.selection_mode_group = QButtonGroup(self)
        self.selection_mode_group.setExclusive(True)
        self.selection_mode_group.addButton(self.smart_select_btn)
        self.selection_mode_group.addButton(self.single_pick_btn)
        self.smart_select_btn.clicked.connect(self._apply_selection_mode)
        self.single_pick_btn.clicked.connect(self._apply_selection_mode)
        self.method_combo = QComboBox(flatten_tab)
        self.method_combo.addItems(["ARAP", "LSCM"])
        self.method_combo.setCurrentText("ARAP")
        self.technical_mode_btn = QPushButton("Technical Mode", flatten_tab)
        self.technical_mode_btn.setCheckable(True)
        self.technical_mode_btn.toggled.connect(self.viewport.set_technical_mode)
        self.show_edges_btn = QPushButton("Show Edges", flatten_tab)
        self.show_edges_btn.setCheckable(True)
        self.show_edges_btn.setChecked(True)
        self.show_edges_btn.toggled.connect(self.viewport.set_edges_visible)
        self.wireframe_btn = QPushButton("Wireframe", flatten_tab)
        self.wireframe_btn.setCheckable(True)
        self.wireframe_btn.toggled.connect(self.viewport.set_wireframe_mode)
        self.selected_label = QLabel("Selected Faces: 0", flatten_tab)
        self.run_flatten_btn = QPushButton("RUN FLATTEN", flatten_tab)
        self.run_flatten_btn.setObjectName("FlattenButton")
        self.run_flatten_btn.setMinimumHeight(42)
        self.run_flatten_btn.clicked.connect(self.run_flatten)
        set_button_icon(self.smart_select_btn, "surface_select")
        set_button_icon(self.single_pick_btn, "pin_vertex")
        set_button_icon(self.clear_selection_btn, "clear_selection")
        set_button_icon(self.invert_selection_btn, "invert_selection")
        set_button_icon(self.isolate_btn, "isolate")
        set_button_icon(self.technical_mode_btn, "strain_map")
        set_button_icon(self.show_edges_btn, "show_edges")
        set_button_icon(self.wireframe_btn, "wireframe")
        set_button_icon(self.run_flatten_btn, "flatten")
        self.quality_gauge = QProgressBar(flatten_tab)
        self.quality_gauge.setRange(0, 100)
        self.quality_gauge.setValue(0)
        self.quality_gauge.setFormat("Quality: -")
        flatten_layout.addWidget(self.smart_select_btn)
        flatten_layout.addWidget(self.single_pick_btn)
        flatten_layout.addWidget(self.clear_selection_btn)
        flatten_layout.addWidget(self.invert_selection_btn)
        flatten_layout.addWidget(self.isolate_btn)
        flatten_layout.addWidget(QLabel("Method:", flatten_tab))
        flatten_layout.addWidget(self.method_combo)
        flatten_layout.addWidget(self.technical_mode_btn)
        flatten_layout.addWidget(self.show_edges_btn)
        flatten_layout.addWidget(self.wireframe_btn)
        flatten_layout.addWidget(self.selected_label)
        flatten_layout.addWidget(self.run_flatten_btn)
        flatten_layout.addWidget(self.quality_gauge, 1)
        tabs.addTab(flatten_tab, "FLATTEN")

        production_tab = QWidget(tabs)
        production_layout = QHBoxLayout(production_tab)
        production_layout.setContentsMargins(10, 10, 10, 10)
        production_layout.setSpacing(8)
        self.seam_slider = QSlider(Qt.Orientation.Horizontal, production_tab)
        self.seam_slider.setRange(0, 200)
        self.seam_slider.setValue(12)
        self.seam_label = QLabel("Seam Allowance: [12] mm", production_tab)
        self.seam_slider.valueChanged.connect(self._on_seam_slider_changed)
        self.nest_btn = QPushButton("Nest on Roll", production_tab)
        self.nest_btn.clicked.connect(self.run_nesting_job)
        set_button_icon(self.nest_btn, "nest")
        self.export_btn = QPushButton("Export DXF", production_tab)
        self.export_btn.clicked.connect(self.export_dxf)
        set_button_icon(self.export_btn, "export_dxf")
        self.export_path_label = QLabel(self.last_export_path or "(last path not set)", production_tab)
        self.export_path_label.setWordWrap(True)
        production_layout.addWidget(self.seam_label)
        production_layout.addWidget(self.seam_slider, 1)
        production_layout.addWidget(self.nest_btn)
        production_layout.addWidget(self.export_btn)
        production_layout.addWidget(self.export_path_label, 1)
        tabs.addTab(production_tab, "PRODUCTION")

        for btn in (
            self.setup_import_btn,
            self.check_scale_btn,
            self.reset_camera_btn,
            self.toggle_2d_btn,
            self.smart_select_btn,
            self.single_pick_btn,
            self.clear_selection_btn,
            self.invert_selection_btn,
            self.isolate_btn,
            self.technical_mode_btn,
            self.show_edges_btn,
            self.wireframe_btn,
            self.nest_btn,
            self.export_btn,
        ):
            btn.setMinimumHeight(36)

        return tabs

    def _build_status_progress(self) -> None:
        status = self.statusBar()
        self.status_meta_label = QLabel("Units: - | Scale: -", self)
        status.addWidget(self.status_meta_label, 1)
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
            total = max(self.viewport_splitter.width(), 1200)
            left = int(total * 0.68)
            right = total - left
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
        margin = 14
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
        self.selected_label.setText(f"Selected Faces: {len(faces)}")
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

        enable = not busy
        self.import_btn.setEnabled(enable)
        self.setup_import_btn.setEnabled(enable)
        self.run_flatten_btn.setEnabled(enable)
        self.run_flatten_btn_top.setEnabled(enable)
        self.export_btn.setEnabled(enable and self.flatten_completed)
        self.export_btn_top.setEnabled(enable and self.flatten_completed)
        self.settings_btn_top.setEnabled(enable)
        self.about_btn_top.setEnabled(enable)
        self.nest_btn.setEnabled(enable and self.flatten_completed)
        self.smart_select_btn.setEnabled(enable)
        self.single_pick_btn.setEnabled(enable)
        self.clear_selection_btn.setEnabled(enable)
        self.invert_selection_btn.setEnabled(enable)
        self.isolate_btn.setEnabled(enable)
        self.technical_mode_btn.setEnabled(enable)
        self.show_edges_btn.setEnabled(enable)
        self.wireframe_btn.setEnabled(enable)
        self.toggle_2d_btn.setEnabled(enable)

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

    def _show_settings_placeholder(self) -> None:
        QMessageBox.information(
            self,
            "Settings",
            "UI settings panel is planned for a later iteration.",
        )

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
        self.seam_label.setText(f"Seam Allowance: [{value}] mm")
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

    def _update_workflow_enablement(self) -> None:
        can_post = bool(self.flatten_completed) and (not self._busy)
        self.export_btn.setEnabled(can_post)
        self.export_btn_top.setEnabled(can_post)
        self.nest_btn.setEnabled(can_post)

    def _update_status_metadata(self) -> None:
        unit = self.units_combo.currentText() if hasattr(self, "units_combo") else "-"
        if self.loaded_vertices is None:
            self.status_meta_label.setText(f"Units: {unit} | Scale: -")
            return
        lx, ly, lz = self._dims_in_mm(self.loaded_vertices)
        self.status_meta_label.setText(f"Units: {unit} | LxWxH: {lx:.1f} x {ly:.1f} x {lz:.1f} mm")

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
