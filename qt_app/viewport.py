from __future__ import annotations

from collections import deque
import math
from typing import Dict, List, Set, Tuple

import numpy as np
from OpenGL import GL as ogl
import pyqtgraph.opengl as gl
from PySide6.QtCore import QPoint, QPointF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QQuaternion, QVector3D, QVector4D
from PySide6.QtWidgets import QLabel, QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget
import trimesh


class OrbitDragButton(QToolButton):
    dragStarted = Signal(QPointF)
    dragMoved = Signal(QPointF)
    dragFinished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dragging = False
        self.setMouseTracking(True)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.dragStarted.emit(event.globalPosition())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self.dragMoved.emit(event.globalPosition())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.dragFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ThreeDViewportWidget(gl.GLViewWidget):
    cameraChanged = Signal(float, float)
    facesSelected = Signal(list)
    modelDropped = Signal(str)
    flattenRequested = Signal()
    splitToggleRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, rotationMethod="quaternion")
        self.setObjectName("ThreeDViewportWidget")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setAutoFillBackground(False)
        self.setMinimumSize(100, 100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setBackgroundColor((178, 184, 192, 255))
        self.setStyleSheet(
            """
            QOpenGLWidget#ThreeDViewportWidget {
                border: none;
                outline: none;
                background-color: transparent;
            }
            """
        )

        self.vertices: np.ndarray | None = None
        self.vertices32: np.ndarray | None = None
        self.render_faces: np.ndarray | None = None
        self.render_faces32: np.ndarray | None = None
        self.pick_faces: np.ndarray | None = None
        self.mesh_name = ""

        self.selection_mode = "single"
        self.selected_faces: Set[int] = set()
        self._hover_face: int | None = None
        self._isolate_mode = False
        self._isolated_pick_indices: Set[int] = set()

        self._drag_start: Tuple[float, float] | None = None
        self._left_dragging = False
        self._nav_last: Tuple[float, float] | None = None
        self._active_nav_mode: str | None = None
        self.is_rotating = False
        self.is_panning = False
        self.is_zooming = False

        self.orbit_mode_enabled = False
        self.pan_mode_enabled = False
        self.zoom_mode_enabled = False
        self._camera_up: Tuple[float, float, float] | None = None

        self._face_normals: np.ndarray | None = None
        self._face_adjacency: List[List[int]] | None = None
        self._vertex_normals: np.ndarray | None = None
        self._pick_cache_token = None
        self._pick_to_render: np.ndarray | None = None
        self._pick_tri_a: np.ndarray | None = None
        self._pick_e1: np.ndarray | None = None
        self._pick_e2: np.ndarray | None = None
        self._hover_pick_indices: np.ndarray | None = None
        self._base_render_face_colors: np.ndarray | None = None
        self._source_vertex_colors: np.ndarray | None = None
        self._source_face_colors: np.ndarray | None = None

        self._pending_hover_pos: Tuple[float, float] | None = None
        self._mesh_center = np.zeros(3, dtype=np.float64)
        self._floating_orbit_last_pos: QPointF | None = None

        self.grid_item = gl.GLGridItem(color=(85, 85, 85, 110))
        self.grid_item.setSize(x=12000.0, y=12000.0, z=1.0)
        self.grid_item.setSpacing(10.0, 10.0, 1.0)
        self.addItem(self.grid_item)

        self.mesh_item = gl.GLMeshItem(drawFaces=True, drawEdges=False, smooth=True, shader="shaded")
        self.mesh_item.opts["smooth"] = True
        self.mesh_item.opts["color"] = (0.70, 0.76, 0.84, 1.0)
        self.mesh_item.setGLOptions("opaque")
        self.addItem(self.mesh_item)

        self.wire_item = gl.GLMeshItem(drawFaces=False, drawEdges=True, smooth=False, shader="shaded")
        self.wire_item.opts["edgeColor"] = (0.0, 0.0, 0.0, 1.0)
        self.wire_item.setGLOptions("translucent")
        self.addItem(self.wire_item)

        self.selection_item = gl.GLMeshItem(
            drawFaces=True,
            drawEdges=False,
            smooth=True,
            shader="shaded",
            glOptions="translucent",
        )
        self.selection_item.setVisible(False)
        self.addItem(self.selection_item)

        self.overlay = QLabel("Drop 3D Model Here\n(STL / OBJ / STEP)", self)
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.setStyleSheet(
            "QLabel { color:#8fa0b7; font-size:24px; font-weight:600; background:transparent; }"
        )
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.dim_label = QLabel("", self)
        self.dim_label.setStyleSheet(
            "QLabel { color:#d5deec; background-color:rgba(20,22,28,170); border:1px solid #3a4250; padding:4px 8px; }"
        )
        self.dim_label.move(14, 14)
        self.dim_label.setMinimumSize(220, 28)
        self.dim_label.show()

        self._camera_debounce = QTimer(self)
        self._camera_debounce.setSingleShot(True)
        self._camera_debounce.setInterval(35)
        self._camera_debounce.timeout.connect(self._emit_camera_changed)

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(25)
        self._hover_timer.timeout.connect(self._process_hover_pick)

        self._build_hud()
        self.clear_view()

    def initializeGL(self) -> None:  # noqa: N802
        super().initializeGL()
        try:
            ogl.glEnable(ogl.GL_DEPTH_TEST)
            ogl.glEnable(ogl.GL_LIGHTING)
            ogl.glEnable(ogl.GL_LIGHT0)
            # Force material tracking so per-vertex/per-face colors are honored under lighting.
            ogl.glEnable(ogl.GL_COLOR_MATERIAL)
            ogl.glEnable(ogl.GL_NORMALIZE)
            ogl.glColorMaterial(ogl.GL_FRONT_AND_BACK, ogl.GL_AMBIENT_AND_DIFFUSE)
            ogl.glLightfv(ogl.GL_LIGHT0, ogl.GL_DIFFUSE, [0.95, 0.95, 0.95, 1.0])
            ogl.glLightfv(ogl.GL_LIGHT0, ogl.GL_AMBIENT, [0.5, 0.5, 0.5, 1.0])
            ogl.glLightfv(ogl.GL_LIGHT0, ogl.GL_SPECULAR, [1.0, 1.0, 1.0, 1.0])
            ogl.glMaterialfv(ogl.GL_FRONT, ogl.GL_SPECULAR, [1.0, 1.0, 1.0, 1.0])
            ogl.glMaterialf(ogl.GL_FRONT, ogl.GL_SHININESS, 50.0)
        except Exception:
            # Some OpenGL backends ignore fixed-function lighting with shader pipelines.
            pass

    def paintGL(self) -> None:  # noqa: N802
        self._update_headlamp_light()
        super().paintGL()
        self._paint_soft_background_gradient()
        self._update_floating_orbit_button_position()

    def _update_headlamp_light(self) -> None:
        try:
            ogl.glEnable(ogl.GL_LIGHTING)
            ogl.glEnable(ogl.GL_LIGHT0)
            ogl.glEnable(ogl.GL_COLOR_MATERIAL)
            ogl.glColorMaterial(ogl.GL_FRONT_AND_BACK, ogl.GL_AMBIENT_AND_DIFFUSE)
            ogl.glLightfv(ogl.GL_LIGHT0, ogl.GL_AMBIENT, [0.5, 0.5, 0.5, 1.0])
            ogl.glLightfv(ogl.GL_LIGHT0, ogl.GL_DIFFUSE, [0.95, 0.95, 0.95, 1.0])
            ogl.glLightfv(ogl.GL_LIGHT0, ogl.GL_SPECULAR, [1.0, 1.0, 1.0, 1.0])
            ogl.glMatrixMode(ogl.GL_MODELVIEW)
            ogl.glPushMatrix()
            ogl.glLoadIdentity()
            # Headlamp at camera origin to keep mesh lit regardless of view direction.
            ogl.glLightfv(ogl.GL_LIGHT0, ogl.GL_POSITION, [0.0, 0.0, 1.0, 0.0])
            ogl.glPopMatrix()
        except Exception:
            pass

    def _paint_soft_background_gradient(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(max(1, self.height())))
        gradient.setColorAt(0.0, QColor(206, 212, 220, 58))
        gradient.setColorAt(1.0, QColor(162, 170, 180, 42))
        painter.fillRect(self.rect(), gradient)
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())
        self.dim_label.raise_()
        self._position_hud()
        self._update_grid_extent()
        self._update_floating_orbit_button_position()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        p = event.position()
        self._nav_last = (float(p.x()), float(p.y()))
        self._drag_start = (float(p.x()), float(p.y()))
        self._left_dragging = False
        self._active_nav_mode = None

        if event.button() == Qt.MouseButton.MiddleButton:
            mods = event.modifiers()
            if (mods & Qt.KeyboardModifier.ControlModifier) and (mods & Qt.KeyboardModifier.AltModifier):
                self._active_nav_mode = "zoom"
                self.is_zooming = True
                self.is_panning = False
                self.is_rotating = False
            elif mods & Qt.KeyboardModifier.AltModifier:
                self._active_nav_mode = "orbit"
                self.is_rotating = True
                self.is_panning = False
                self.is_zooming = False
            elif self.zoom_mode_enabled:
                self._active_nav_mode = "zoom"
                self.is_zooming = True
                self.is_panning = False
                self.is_rotating = False
            elif self.orbit_mode_enabled:
                self._active_nav_mode = "orbit"
                self.is_rotating = True
                self.is_panning = False
                self.is_zooming = False
            else:
                self._active_nav_mode = "pan"
                self.is_panning = True
                self.is_rotating = False
                self.is_zooming = False
            event.accept()
            return

        # Selection is LMB click only.
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        cur = (float(event.position().x()), float(event.position().y()))
        if self._nav_last is None:
            self._nav_last = cur
        dx = cur[0] - self._nav_last[0]
        dy = cur[1] - self._nav_last[1]
        self._nav_last = cur

        if self.is_rotating and self._active_nav_mode == "orbit":
            self.orbit(-dx, dy)
            self._on_camera_event()
            event.accept()
            return
        if self.is_panning and self._active_nav_mode == "pan":
            self.pan(dx, dy, 0.0, relative="view-upright")
            self._on_camera_event()
            event.accept()
            return
        if self.is_zooming and self._active_nav_mode == "zoom":
            self._zoom_camera_by_delta(dy)
            self._on_camera_event()
            event.accept()
            return

        if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_start is not None:
            ddx = cur[0] - self._drag_start[0]
            ddy = cur[1] - self._drag_start[1]
            if (ddx * ddx + ddy * ddy) > 25.0:
                self._left_dragging = True
            event.accept()
            return

        # Free hover feedback when no buttons are pressed.
        if event.buttons() == Qt.MouseButton.NoButton:
            self._schedule_hover_pick(cur[0], cur[1])
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton and self.is_rotating:
            self.is_rotating = False
            self._nav_last = None
            self._active_nav_mode = None
            self._on_camera_event()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton and self.is_panning:
            self.is_panning = False
            self._nav_last = None
            self._active_nav_mode = None
            self._on_camera_event()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton and self.is_zooming:
            self.is_zooming = False
            self._nav_last = None
            self._active_nav_mode = None
            self._on_camera_event()
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            try:
                if self.selection_mode == "off" or self.vertices is None or self.pick_faces is None or self._left_dragging:
                    event.accept()
                    return
                hit = self._raycast_face(float(event.position().x()), float(event.position().y()))
                mods = event.modifiers()
                ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
                alt = bool(mods & Qt.KeyboardModifier.AltModifier)
                if hit is None:
                    if not ctrl and not alt:
                        self.selected_faces.clear()
                        self._update_mesh_visuals()
                        self.facesSelected.emit(self.get_selected_faces())
                    event.accept()
                    return

                new_faces = {int(hit)} if self.selection_mode == "single" else self.smart_select(int(hit), 30.0)
                if alt:
                    self.selected_faces.difference_update(new_faces)
                elif ctrl:
                    self.selected_faces.update(new_faces)
                else:
                    self.selected_faces = set(new_faces)

                if self._isolate_mode and self._isolated_pick_indices:
                    self._isolated_pick_indices = set(self.selected_faces)

                self._update_mesh_visuals()
                self.facesSelected.emit(self.get_selected_faces())
                event.accept()
                return
            finally:
                self._drag_start = None
                self._left_dragging = False

        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = int(event.angleDelta().x()) or int(event.angleDelta().y())
        self.opts["distance"] = float(np.clip(self.opts["distance"] * (0.999 ** delta), 1e-3, 1e12))
        self.update()
        self._on_camera_event()
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Z:
            self._frame_selected_region()
            event.accept()
            return
        if event.key() == Qt.Key.Key_W and (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self.splitToggleRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                p = urls[0].toLocalFile().lower()
                if p.endswith(".stl") or p.endswith(".obj") or p.endswith(".stp") or p.endswith(".step"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            self.modelDropped.emit(urls[0].toLocalFile())
            event.acceptProposedAction()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self._show_context_menu(event.globalPos())

    def _build_hud(self) -> None:
        self.hud = QWidget(self)
        self.hud.setObjectName("ViewportHUD")
        self.hud.setStyleSheet(
            """
            QWidget#ViewportHUD {
                background-color: rgba(0, 0, 0, 150);
                border-radius: 8px;
            }
            QToolButton {
                min-width:30px;
                min-height:30px;
                max-width:30px;
                max-height:30px;
                color:#f2f2f2;
                background-color:#2a2a2a;
                border:1px solid #565656;
                border-radius:4px;
                font-size:15px;
            }
            QToolButton:checked {
                border-color:#cfcfcf;
                background-color:#3c3c3c;
            }
            """
        )
        hud_layout = QVBoxLayout(self.hud)
        hud_layout.setContentsMargins(8, 8, 8, 8)
        hud_layout.setSpacing(6)

        self.hud_fit_btn = QToolButton(self.hud)
        self.hud_fit_btn.setText("\u26F6")
        self.hud_fit_btn.setToolTip("Zoom Fit")
        self.hud_fit_btn.clicked.connect(self.reset_camera)

        self.hud_pan_btn = QToolButton(self.hud)
        self.hud_pan_btn.setText("\u270B")
        self.hud_pan_btn.setToolTip("Pan Override")
        self.hud_pan_btn.setCheckable(True)
        self.hud_pan_btn.toggled.connect(self._toggle_pan_mode)

        self.hud_zoom_btn = QToolButton(self.hud)
        self.hud_zoom_btn.setText("\u21F5")
        self.hud_zoom_btn.setToolTip("Zoom Override")
        self.hud_zoom_btn.setCheckable(True)
        self.hud_zoom_btn.toggled.connect(self._toggle_zoom_mode)

        self.hud_orbit_btn = QToolButton(self.hud)
        self.hud_orbit_btn.setText("\u21BB")
        self.hud_orbit_btn.setToolTip("Orbit Override")
        self.hud_orbit_btn.setCheckable(True)
        self.hud_orbit_btn.setChecked(False)
        self.hud_orbit_btn.toggled.connect(self._toggle_orbit_mode)

        self.hud_split_btn = QToolButton(self.hud)
        self.hud_split_btn.setText("\u25EB")
        self.hud_split_btn.setToolTip("Toggle 2D Preview")
        self.hud_split_btn.clicked.connect(self.splitToggleRequested.emit)

        for btn in (self.hud_fit_btn, self.hud_pan_btn, self.hud_zoom_btn, self.hud_orbit_btn, self.hud_split_btn):
            hud_layout.addWidget(btn)
        self.hud.adjustSize()
        self.hud.show()

        self.floating_orbit_btn = OrbitDragButton(self)
        self.floating_orbit_btn.setObjectName("FloatingOrbitButton")
        self.floating_orbit_btn.setText("\u21BB")
        self.floating_orbit_btn.setToolTip("Drag to Orbit Around Model")
        self.floating_orbit_btn.setCursor(Qt.CursorShape.OpenHandCursor)
        self.floating_orbit_btn.setFixedSize(36, 36)
        self.floating_orbit_btn.setStyleSheet(
            """
            QToolButton#FloatingOrbitButton {
                color: #f2f2f2;
                font-size: 17px;
                font-weight: 600;
                border: none;
                border-radius: 18px;
                background-color: rgba(38, 38, 38, 120);
            }
            QToolButton#FloatingOrbitButton:hover {
                background-color: rgba(52, 52, 52, 145);
            }
            QToolButton#FloatingOrbitButton:pressed {
                background-color: rgba(24, 24, 24, 170);
            }
            """
        )
        self.floating_orbit_btn.dragStarted.connect(self._on_floating_orbit_drag_started)
        self.floating_orbit_btn.dragMoved.connect(self._on_floating_orbit_drag_moved)
        self.floating_orbit_btn.dragFinished.connect(self._on_floating_orbit_drag_finished)
        self.floating_orbit_btn.hide()
        self._position_hud()

    def _position_hud(self) -> None:
        margin = 16
        self.hud.move(max(0, self.width() - self.hud.width() - margin), max(0, self.height() - self.hud.height() - margin))
        self.hud.raise_()
        if hasattr(self, "floating_orbit_btn"):
            self.floating_orbit_btn.raise_()
        self.dim_label.raise_()

    def _on_floating_orbit_drag_started(self, global_pos: QPointF) -> None:
        self._floating_orbit_last_pos = QPointF(global_pos)
        self.floating_orbit_btn.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _on_floating_orbit_drag_moved(self, global_pos: QPointF) -> None:
        if self._floating_orbit_last_pos is None:
            self._floating_orbit_last_pos = QPointF(global_pos)
            return
        dx = float(global_pos.x() - self._floating_orbit_last_pos.x())
        dy = float(global_pos.y() - self._floating_orbit_last_pos.y())
        self._floating_orbit_last_pos = QPointF(global_pos)
        self.orbit(-dx, dy)
        self._on_camera_event()

    def _on_floating_orbit_drag_finished(self) -> None:
        self._floating_orbit_last_pos = None
        self.floating_orbit_btn.setCursor(Qt.CursorShape.OpenHandCursor)
        self._on_camera_event()

    def mapFrom3D(self, point_3d: np.ndarray | Tuple[float, float, float] | QVector3D) -> QPoint:
        w = max(1, int(self.width()))
        h = max(1, int(self.height()))

        if isinstance(point_3d, QVector3D):
            p = QVector4D(point_3d.x(), point_3d.y(), point_3d.z(), 1.0)
        else:
            arr = np.asarray(point_3d, dtype=np.float64)
            p = QVector4D(float(arr[0]), float(arr[1]), float(arr[2]), 1.0)

        proj = self.projectionMatrix((0, 0, w, h), self.getViewport())
        view = self.viewMatrix()
        clip = proj.map(view.map(p))
        cw = float(clip.w())
        if abs(cw) < 1e-9:
            return QPoint(w // 2, h // 2)

        ndc_x = float(clip.x()) / cw
        ndc_y = float(clip.y()) / cw
        sx = int(round((ndc_x + 1.0) * 0.5 * w))
        sy = int(round((1.0 - ndc_y) * 0.5 * h))
        return QPoint(sx, sy)

    def _update_floating_orbit_button_position(self) -> None:
        if not hasattr(self, "floating_orbit_btn"):
            return
        if self.vertices is None:
            self.floating_orbit_btn.hide()
            return

        anchor = self.mapFrom3D(self._mesh_center)
        btn = self.floating_orbit_btn
        margin = 8
        x = max(margin, min(self.width() - btn.width() - margin, anchor.x() + 16))
        y = max(margin, min(self.height() - btn.height() - margin, anchor.y() + 16))
        btn.move(int(x), int(y))
        btn.show()
        btn.raise_()

    def _toggle_pan_mode(self, enabled: bool) -> None:
        self.pan_mode_enabled = bool(enabled)
        if enabled:
            self.hud_orbit_btn.blockSignals(True)
            self.hud_orbit_btn.setChecked(False)
            self.hud_orbit_btn.blockSignals(False)
            self.hud_zoom_btn.blockSignals(True)
            self.hud_zoom_btn.setChecked(False)
            self.hud_zoom_btn.blockSignals(False)
            self.orbit_mode_enabled = False
            self.zoom_mode_enabled = False
        self.is_panning = False
        self._active_nav_mode = None
        self._nav_last = None

    def _toggle_orbit_mode(self, enabled: bool) -> None:
        self.orbit_mode_enabled = bool(enabled)
        if enabled:
            self.hud_pan_btn.blockSignals(True)
            self.hud_pan_btn.setChecked(False)
            self.hud_pan_btn.blockSignals(False)
            self.hud_zoom_btn.blockSignals(True)
            self.hud_zoom_btn.setChecked(False)
            self.hud_zoom_btn.blockSignals(False)
            self.pan_mode_enabled = False
            self.zoom_mode_enabled = False
        self.is_rotating = False
        self._active_nav_mode = None
        self._nav_last = None

    def _toggle_zoom_mode(self, enabled: bool) -> None:
        self.zoom_mode_enabled = bool(enabled)
        if enabled:
            self.hud_pan_btn.blockSignals(True)
            self.hud_pan_btn.setChecked(False)
            self.hud_pan_btn.blockSignals(False)
            self.hud_orbit_btn.blockSignals(True)
            self.hud_orbit_btn.setChecked(False)
            self.hud_orbit_btn.blockSignals(False)
            self.pan_mode_enabled = False
            self.orbit_mode_enabled = False
        self.is_zooming = False
        self._active_nav_mode = None
        self._nav_last = None

    def _zoom_camera_by_delta(self, dy: float) -> None:
        factor = 1.0 + (float(dy) * 0.01)
        factor = max(0.2, min(5.0, factor))
        self.opts["distance"] = float(np.clip(self.opts["distance"] * factor, 1e-3, 1e12))
        self.update()

    def clear_view(self) -> None:
        self.vertices = None
        self.vertices32 = None
        self.render_faces = None
        self.render_faces32 = None
        self.pick_faces = None
        self.selected_faces.clear()
        self._hover_face = None
        self._isolate_mode = False
        self._isolated_pick_indices.clear()

        self._face_normals = None
        self._face_adjacency = None
        self._vertex_normals = None
        self._pick_cache_token = None
        self._pick_to_render = None
        self._pick_tri_a = None
        self._pick_e1 = None
        self._pick_e2 = None
        self._hover_pick_indices = None
        self._base_render_face_colors = None
        self._source_vertex_colors = None
        self._source_face_colors = None
        self._mesh_center = np.zeros(3, dtype=np.float64)
        self._floating_orbit_last_pos = None

        self.mesh_item.setMeshData(
            vertexes=np.empty((0, 3), dtype=np.float32),
            faces=np.empty((0, 3), dtype=np.int32),
            shader="shaded",
            smooth=True,
            drawEdges=False,
        )
        self.mesh_item.opts["smooth"] = True
        self.mesh_item.opts["color"] = (0.70, 0.76, 0.84, 1.0)
        self.wire_item.setMeshData(
            vertexes=np.empty((0, 3), dtype=np.float32),
            faces=np.empty((0, 3), dtype=np.int32),
            drawFaces=False,
            drawEdges=True,
            edgeColor=(0.0, 0.0, 0.0, 1.0),
        )
        self.wire_item.opts["edgeColor"] = (0.0, 0.0, 0.0, 1.0)
        self.selection_item.setVisible(False)

        self.setCameraPosition(pos=QVector3D(0.0, 0.0, 0.0), distance=600.0, elevation=24.0, azimuth=-58.0)
        self.opts["fov"] = 45.0
        self._camera_up = (0.0, 0.0, 1.0)
        self._update_grid_extent()
        self.overlay.show()
        self.dim_label.setText("")
        self.floating_orbit_btn.hide()
        self.update()

    def set_mesh(
        self,
        name: str,
        vertices: np.ndarray,
        render_faces: np.ndarray,
        dims_mm: Tuple[float, float, float],
        pick_faces: np.ndarray | None = None,
        vertex_colors: np.ndarray | None = None,
        face_colors: np.ndarray | None = None,
    ) -> None:
        self.mesh_name = name
        self.vertices = np.asarray(vertices, dtype=np.float64)
        self._mesh_center = self.vertices.mean(axis=0)
        self.vertices32 = np.ascontiguousarray(self.vertices.astype(np.float32, copy=False))
        self.render_faces = np.asarray(render_faces, dtype=np.int64)
        self.render_faces32 = np.ascontiguousarray(self.render_faces.astype(np.int32, copy=False))
        self.pick_faces = np.asarray(pick_faces, dtype=np.int64) if pick_faces is not None else self.render_faces

        self.selected_faces.clear()
        self._hover_face = None
        self._isolate_mode = False
        self._isolated_pick_indices.clear()
        self._face_normals = None
        self._face_adjacency = None
        self._pick_cache_token = (len(self.vertices), len(self.pick_faces))
        self._source_vertex_colors = self._normalize_color_array(vertex_colors, expected_len=len(self.vertices))
        self._source_face_colors = self._normalize_color_array(face_colors, expected_len=len(self.render_faces))
        if self._looks_like_default_gray(self._source_vertex_colors):
            self._source_vertex_colors = None
        if self._looks_like_default_gray(self._source_face_colors):
            self._source_face_colors = None

        self._vertex_normals = self._compute_vertex_normals_from_trimesh()
        self._base_render_face_colors = self._build_source_face_colors()
        if self._base_render_face_colors is None:
            self._base_render_face_colors = self._build_default_face_colors()
        self._build_pick_to_render_map()
        self._prepare_pick_raycast_cache()
        self._update_mesh_visuals()
        self._fit_camera_to_mesh()
        self._update_grid_extent()

        lx, ly, lz = dims_mm
        self.dim_label.setText(f"{name} | LxWxH: {lx:.1f} x {ly:.1f} x {lz:.1f} mm")
        self.overlay.hide()
        self._on_camera_event()

    # Compatibility alias used in CAD viewport directives.
    def update_model(self, vertices: np.ndarray, faces: np.ndarray, mesh: trimesh.Trimesh | None = None) -> None:
        verts = np.asarray(vertices, dtype=np.float64)
        tri_faces = np.asarray(faces, dtype=np.int64)
        dims = verts.max(axis=0) - verts.min(axis=0)

        source_vertex_colors = None
        source_face_colors = None
        if mesh is not None:
            source_vertex_colors, source_face_colors = self._extract_source_colors_from_mesh(mesh, tri_faces)
            source_vertex_colors = self._normalize_color_array(source_vertex_colors, expected_len=len(verts))
            source_face_colors = self._normalize_color_array(source_face_colors, expected_len=len(tri_faces))

        self.set_mesh(
            self.mesh_name or "Model",
            verts,
            tri_faces,
            (float(dims[0]), float(dims[1]), float(dims[2])),
            pick_faces=tri_faces,
            vertex_colors=source_vertex_colors,
            face_colors=source_face_colors,
        )

    def _fit_camera_to_mesh(self) -> None:
        if self.vertices is None:
            return
        mins = self.vertices.min(axis=0)
        maxs = self.vertices.max(axis=0)
        center = (mins + maxs) * 0.5
        self._mesh_center = center
        span_xyz = maxs - mins
        span = float(max(np.max(span_xyz), np.linalg.norm(span_xyz), 1.0))
        self.setCameraPosition(
            pos=QVector3D(float(center[0]), float(center[1]), float(center[2])),
            distance=max(span * 1.8, 20.0),
            elevation=24.0,
            azimuth=-58.0,
        )
        self.opts["fov"] = 40.0
        self._camera_up = (0.0, 0.0, 1.0)
        self.update()

    def reset_camera(self) -> None:
        if self.vertices is not None:
            self._fit_camera_to_mesh()
        else:
            self.clear_view()
        self._on_camera_event()

    def apply_view_preset(self, preset: str) -> None:
        if self.vertices is None:
            return
        mins = self.vertices.min(axis=0)
        maxs = self.vertices.max(axis=0)
        center = (mins + maxs) * 0.5
        self._mesh_center = center
        dist = max(float(np.max(maxs - mins)) * 2.2, 20.0)

        mapping = {
            "FRONT": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
            "BACK": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            "LEFT": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            "RIGHT": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            "TOP": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
            "BOTTOM": ((0.0, 0.0, -1.0), (0.0, -1.0, 0.0)),
        }
        if preset not in mapping:
            return

        direction, up = mapping[preset]
        dir_vec = QVector3D(float(direction[0]), float(direction[1]), float(direction[2]))
        up_vec = QVector3D(float(up[0]), float(up[1]), float(up[2]))
        rot = QQuaternion.fromDirection(-dir_vec, up_vec)

        self.setCameraPosition(
            pos=QVector3D(float(center[0]), float(center[1]), float(center[2])),
            distance=dist,
            rotation=rot,
        )
        self.opts["fov"] = 40.0
        self._camera_up = up
        self.update()
        self._on_camera_event()

    def set_selection_mode(self, mode: str) -> None:
        self.selection_mode = mode

    def clear_selection(self) -> None:
        if not self.selected_faces:
            return
        self.selected_faces.clear()
        if self._isolate_mode:
            self._isolated_pick_indices.clear()
        self._update_mesh_visuals()
        self.facesSelected.emit([])

    def get_selected_faces(self) -> List[int]:
        return sorted(self.selected_faces)

    def _on_camera_event(self) -> None:
        self._camera_debounce.start()
        self._update_floating_orbit_button_position()

    def _emit_camera_changed(self) -> None:
        center = self.opts["center"]
        cam = self.cameraPosition()
        vx = float(cam.x() - center.x())
        vy = float(cam.y() - center.y())
        vz = float(cam.z() - center.z())
        elev = float(math.degrees(math.atan2(vz, max(math.hypot(vx, vy), 1e-12))))
        azim = float(math.degrees(math.atan2(vy, vx)))
        self.cameraChanged.emit(elev, azim)
        self._update_floating_orbit_button_position()

    def _frame_selected_region(self) -> None:
        if self.vertices is None:
            return
        if self.selected_faces and self.pick_faces is not None:
            idx = np.asarray(sorted(self.selected_faces), dtype=np.int64)
            idx = idx[(idx >= 0) & (idx < len(self.pick_faces))]
            if len(idx):
                used_vertices = np.unique(self.pick_faces[idx].reshape(-1))
                verts = self.vertices[used_vertices]
            else:
                verts = self.vertices
        else:
            verts = self.vertices

        mins = verts.min(axis=0)
        maxs = verts.max(axis=0)
        center = (mins + maxs) * 0.5
        diag = float(np.linalg.norm(maxs - mins))
        dist = max(diag * 1.5, 1.0)
        self.setCameraPosition(pos=QVector3D(float(center[0]), float(center[1]), float(center[2])), distance=dist)
        self.update()
        self._on_camera_event()

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        clear_action = menu.addAction("Clear Selection")
        invert_action = menu.addAction("Invert Selection")
        isolate_action = menu.addAction("Exit Isolate" if self._isolate_mode else "Isolate")
        flatten_action = menu.addAction("Flatten Selected")
        chosen = menu.exec(global_pos)
        if chosen == clear_action:
            self.clear_selection()
        elif chosen == invert_action:
            self._invert_selection()
        elif chosen == isolate_action:
            self._toggle_isolate()
        elif chosen == flatten_action:
            self.flattenRequested.emit()

    def _invert_selection(self) -> None:
        if self.pick_faces is None:
            return
        all_faces = set(range(len(self.pick_faces)))
        self.selected_faces = all_faces.difference(self.selected_faces)
        if self._isolate_mode:
            self._isolated_pick_indices = set(self.selected_faces)
        self._update_mesh_visuals()
        self.facesSelected.emit(self.get_selected_faces())

    def _toggle_isolate(self) -> None:
        if not self._isolate_mode:
            if not self.selected_faces:
                return
            self._isolate_mode = True
            self._isolated_pick_indices = set(self.selected_faces)
        else:
            self._isolate_mode = False
            self._isolated_pick_indices.clear()
        self._update_mesh_visuals()

    def _update_grid_extent(self) -> None:
        if self.vertices is None:
            span = 3500.0
            cx = 0.0
            cy = 0.0
        else:
            mins = self.vertices.min(axis=0)
            maxs = self.vertices.max(axis=0)
            span = max(float(np.max(maxs - mins)) * 8.0, 800.0)
            cx = float((mins[0] + maxs[0]) * 0.5)
            cy = float((mins[1] + maxs[1]) * 0.5)

        aspect = max(1.0, float(self.width()) / max(1.0, float(self.height())))
        x_size = max(2000.0, min(200000.0, span * aspect * 2.0))
        y_size = max(2000.0, min(200000.0, span * 2.0))
        step = max(10.0, round((span / 80.0) / 10.0) * 10.0)

        self.grid_item.resetTransform()
        self.grid_item.setSize(x=x_size, y=y_size, z=1.0)
        self.grid_item.setSpacing(step, step, 1.0)
        self.grid_item.setColor((85, 85, 85, 110))
        self.grid_item.translate(cx, cy, 0.0)

    def _compute_vertex_normals_from_trimesh(self) -> np.ndarray | None:
        if self.vertices is None or self.render_faces is None:
            return None
        try:
            tri_mesh = trimesh.Trimesh(vertices=self.vertices, faces=self.render_faces, process=False)
            vn = np.asarray(tri_mesh.vertex_normals, dtype=np.float64)
            if len(vn) == len(self.vertices):
                return vn
        except Exception:
            pass
        return self._compute_vertex_normals_fallback()

    def _compute_vertex_normals_fallback(self) -> np.ndarray | None:
        if self.vertices is None or self.render_faces is None:
            return None
        vn = np.zeros_like(self.vertices, dtype=np.float64)
        tri = self.vertices[self.render_faces]
        fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        for i, face in enumerate(self.render_faces):
            vn[face[0]] += fn[i]
            vn[face[1]] += fn[i]
            vn[face[2]] += fn[i]
        lens = np.linalg.norm(vn, axis=1)
        lens = np.where(lens < 1e-12, 1e-12, lens)
        return vn / lens[:, None]

    def _normalize_color_array(self, colors: np.ndarray | None, expected_len: int | None = None) -> np.ndarray | None:
        if colors is None:
            return None
        arr = np.asarray(colors)
        if arr.size == 0:
            return None
        if arr.ndim == 1:
            if arr.shape[0] not in (3, 4):
                return None
            arr = arr.reshape(1, -1)
        if arr.ndim != 2 or arr.shape[1] not in (3, 4):
            return None

        arr = arr.astype(np.float32, copy=False)
        if arr.shape[1] == 3:
            alpha = np.ones((arr.shape[0], 1), dtype=np.float32)
            arr = np.concatenate((arr, alpha), axis=1)

        if np.issubdtype(np.asarray(colors).dtype, np.integer) or float(np.max(arr)) > 1.001:
            arr = arr / 255.0
        arr = np.clip(arr, 0.0, 1.0).astype(np.float32, copy=False)

        if expected_len is not None and len(arr) != expected_len:
            if len(arr) == 1:
                arr = np.tile(arr, (expected_len, 1))
            else:
                return None
        return arr

    def _looks_like_default_gray(self, colors: np.ndarray | None) -> bool:
        if colors is None or len(colors) == 0:
            return False
        rgb = np.asarray(colors[:, :3], dtype=np.float32)
        # trimesh default for "no color" is typically [102, 102, 102, 255]
        default = np.array([102.0 / 255.0, 102.0 / 255.0, 102.0 / 255.0], dtype=np.float32)
        channel_spread = float(np.max(np.abs(rgb - rgb[:, :1])))
        mean_rgb = np.mean(rgb, axis=0)
        close_to_default = bool(np.all(np.abs(mean_rgb - default) < 0.03))
        nearly_uniform = bool(float(np.max(np.std(rgb, axis=0))) < 0.015)
        return close_to_default and nearly_uniform and channel_spread < 0.02

    def _extract_source_colors_from_mesh(
        self, mesh: trimesh.Trimesh, target_faces: np.ndarray
    ) -> Tuple[np.ndarray | None, np.ndarray | None]:
        try:
            visual = getattr(mesh, "visual", None)
        except Exception:
            visual = None
        if visual is None:
            return None, None
        if not bool(getattr(visual, "defined", False)):
            return None, None

        vertex_colors = self._normalize_color_array(
            getattr(visual, "vertex_colors", None),
            expected_len=len(getattr(mesh, "vertices", [])),
        )
        raw_face_colors = self._normalize_color_array(
            getattr(visual, "face_colors", None),
            expected_len=len(getattr(mesh, "faces", [])),
        )
        if raw_face_colors is None:
            if self._looks_like_default_gray(vertex_colors):
                return None, None
            return vertex_colors, None

        mesh_faces = np.asarray(getattr(mesh, "faces", []), dtype=np.int64)
        if (
            len(mesh_faces) == len(target_faces)
            and mesh_faces.shape == target_faces.shape
            and np.array_equal(mesh_faces, target_faces)
        ):
            return vertex_colors, raw_face_colors

        # Remap colors for downsampled or reordered face arrays.
        key_to_idx = {tuple(sorted(map(int, f))): i for i, f in enumerate(mesh_faces)}
        remapped = np.empty((len(target_faces), 4), dtype=np.float32)
        hit_count = 0
        for i, tri in enumerate(target_faces):
            idx = key_to_idx.get(tuple(sorted(map(int, tri))), -1)
            if idx >= 0:
                remapped[i] = raw_face_colors[idx]
                hit_count += 1
            else:
                remapped[i] = np.array([0.68, 0.70, 0.75, 1.0], dtype=np.float32)
        if hit_count == 0:
            if self._looks_like_default_gray(vertex_colors):
                return None, None
            return vertex_colors, None
        if self._looks_like_default_gray(vertex_colors):
            vertex_colors = None
        if self._looks_like_default_gray(remapped):
            remapped = None
        return vertex_colors, remapped

    def _build_source_face_colors(self) -> np.ndarray | None:
        if self.render_faces is None:
            return None
        if self._source_face_colors is not None and len(self._source_face_colors) == len(self.render_faces):
            return self._source_face_colors.copy()
        if self._source_vertex_colors is None or self.vertices is None:
            return None
        if len(self._source_vertex_colors) != len(self.vertices):
            return None
        mapped = self._source_vertex_colors[self.render_faces].mean(axis=1)
        return np.clip(mapped, 0.0, 1.0).astype(np.float32, copy=False)

    def _face_colors_to_vertex_colors(self, face_colors: np.ndarray) -> np.ndarray:
        if self.vertices is None or self.render_faces is None or len(self.vertices) == 0:
            return np.empty((0, 4), dtype=np.float32)
        vc = np.zeros((len(self.vertices), 4), dtype=np.float32)
        counts = np.zeros((len(self.vertices),), dtype=np.float32)
        faces = self.render_faces
        cols = np.asarray(face_colors, dtype=np.float32)
        for i, tri in enumerate(faces):
            c = cols[i]
            a, b, c_idx = int(tri[0]), int(tri[1]), int(tri[2])
            vc[a] += c
            vc[b] += c
            vc[c_idx] += c
            counts[a] += 1.0
            counts[b] += 1.0
            counts[c_idx] += 1.0
        counts = np.where(counts <= 0.0, 1.0, counts)
        vc /= counts[:, None]
        return np.clip(vc, 0.0, 1.0).astype(np.float32, copy=False)

    def _build_default_face_colors(self) -> np.ndarray:
        if self.vertices is None or self.render_faces is None or len(self.render_faces) == 0:
            return np.empty((0, 4), dtype=np.float32)

        cad_blue = np.array([100.0 / 255.0, 150.0 / 255.0, 220.0 / 255.0], dtype=np.float32)
        base = np.tile(cad_blue[None, :], (len(self.render_faces), 1))

        # Use normals to add depth while retaining a clear CAD-blue fallback tone.
        if self._vertex_normals is not None and len(self._vertex_normals) == len(self.vertices):
            vn_faces = self._vertex_normals[self.render_faces].mean(axis=1)
            vn_norm = np.linalg.norm(vn_faces, axis=1)
            vn_norm = np.where(vn_norm < 1e-12, 1e-12, vn_norm)
            vn_faces = vn_faces / vn_norm[:, None]
            light_dir = np.array([1.0, 1.0, 1.0], dtype=np.float64)
            light_dir = light_dir / np.linalg.norm(light_dir)
            diffuse = np.clip(np.einsum("ij,j->i", vn_faces, light_dir), 0.0, 1.0)
            shade = (0.72 + 0.28 * diffuse).astype(np.float32)
            base = np.clip(base * shade[:, None] + 0.08, 0.0, 1.0)

        alpha = np.full((len(base), 1), 0.98, dtype=np.float32)
        return np.concatenate((base.astype(np.float32), alpha), axis=1)

    def _build_pick_to_render_map(self) -> None:
        if self.pick_faces is None or self.render_faces is None:
            self._pick_to_render = None
            return
        if len(self.pick_faces) == len(self.render_faces) and np.array_equal(self.pick_faces, self.render_faces):
            self._pick_to_render = np.arange(len(self.pick_faces), dtype=np.int64)
            return
        render_map = {tuple(sorted(map(int, f))): i for i, f in enumerate(self.render_faces)}
        self._pick_to_render = np.array(
            [render_map.get(tuple(sorted(map(int, f))), -1) for f in self.pick_faces],
            dtype=np.int64,
        )

    def _prepare_pick_raycast_cache(self) -> None:
        if self.vertices is None or self.pick_faces is None or len(self.pick_faces) == 0:
            self._pick_tri_a = None
            self._pick_e1 = None
            self._pick_e2 = None
            self._hover_pick_indices = None
            return

        tri = self.vertices[self.pick_faces]
        self._pick_tri_a = tri[:, 0, :]
        self._pick_e1 = tri[:, 1, :] - tri[:, 0, :]
        self._pick_e2 = tri[:, 2, :] - tri[:, 0, :]

        n_faces = len(self.pick_faces)
        if n_faces > 8000:
            step = int(math.ceil(n_faces / 8000.0))
            self._hover_pick_indices = np.arange(0, n_faces, step, dtype=np.int64)
        else:
            self._hover_pick_indices = None

    def _update_mesh_visuals(self) -> None:
        if self.vertices32 is None or self.render_faces32 is None:
            return
        colors = self._base_render_face_colors.copy() if self._base_render_face_colors is not None else self._build_default_face_colors()

        if self._isolate_mode and self._pick_to_render is not None and self._isolated_pick_indices:
            mask = np.zeros(len(colors), dtype=bool)
            iso = np.asarray(sorted(self._isolated_pick_indices), dtype=np.int64)
            iso = iso[(iso >= 0) & (iso < len(self._pick_to_render))]
            ridx_iso = self._pick_to_render[iso]
            ridx_iso = ridx_iso[ridx_iso >= 0]
            if len(ridx_iso):
                mask[ridx_iso] = True
                colors[~mask, :3] *= 0.15
                colors[~mask, 3] = 0.08

        if self._hover_face is not None and self._pick_to_render is not None:
            if 0 <= self._hover_face < len(self._pick_to_render):
                ridx_hover = int(self._pick_to_render[self._hover_face])
                if ridx_hover >= 0 and self._hover_face not in self.selected_faces:
                    colors[ridx_hover] = np.array([0.96, 0.96, 0.36, 1.0], dtype=np.float32)

        if self._pick_to_render is not None and self.selected_faces:
            idx = np.asarray(sorted(self.selected_faces), dtype=np.int64)
            idx = idx[(idx >= 0) & (idx < len(self._pick_to_render))]
            ridx = self._pick_to_render[idx]
            ridx = ridx[ridx >= 0]
            if len(ridx):
                colors[ridx] = np.array([1.0, 0.42, 0.05, 1.0], dtype=np.float32)

        vertex_colors = self._face_colors_to_vertex_colors(colors)

        self.mesh_item.setMeshData(
            vertexes=self.vertices32,
            faces=self.render_faces32,
            vertexColors=vertex_colors,
            smooth=True,
            drawEdges=False,
            shader="shaded",
        )
        self.mesh_item.opts["smooth"] = True
        self.mesh_item.opts["color"] = (0.70, 0.76, 0.84, 1.0)
        self.mesh_item.setGLOptions("opaque")

        center = self._mesh_center.astype(np.float32, copy=False)
        wire_vertices = np.ascontiguousarray((self.vertices32 - center[None, :]) * 1.001 + center[None, :], dtype=np.float32)
        self.wire_item.setMeshData(
            vertexes=wire_vertices,
            faces=self.render_faces32,
            drawFaces=False,
            drawEdges=True,
            edgeColor=(0.0, 0.0, 0.0, 1.0),
        )
        self.wire_item.opts["edgeColor"] = (0.0, 0.0, 0.0, 1.0)
        self.wire_item.setGLOptions("translucent")

        if self.selected_faces and self.pick_faces is not None and self.vertices32 is not None:
            idx = np.asarray(sorted(self.selected_faces), dtype=np.int64)
            idx = idx[(idx >= 0) & (idx < len(self.pick_faces))]
            if len(idx):
                sel_faces = np.ascontiguousarray(self.pick_faces[idx].astype(np.int32, copy=False))
                sel_colors = np.tile(np.array([1.0, 0.45, 0.0, 0.35], dtype=np.float32), (len(sel_faces), 1))
                self.selection_item.setMeshData(
                    vertexes=self.vertices32,
                    faces=sel_faces,
                    faceColors=sel_colors,
                    smooth=True,
                    drawEdges=False,
                    shader="shaded",
                )
                self.selection_item.setVisible(True)
            else:
                self.selection_item.setVisible(False)
        else:
            self.selection_item.setVisible(False)

        self.update()

    def _schedule_hover_pick(self, sx: float, sy: float) -> None:
        self._pending_hover_pos = (float(sx), float(sy))
        if not self._hover_timer.isActive():
            self._hover_timer.start()

    def _process_hover_pick(self) -> None:
        if self._pending_hover_pos is None or self.pick_faces is None:
            return
        sx, sy = self._pending_hover_pos
        hit = self._raycast_face(sx, sy, face_indices=self._hover_pick_indices)
        if hit != self._hover_face:
            self._hover_face = hit
            self._update_mesh_visuals()

    def _screen_ray(self, sx: float, sy: float) -> Tuple[np.ndarray, np.ndarray] | None:
        w = max(1, int(self.width()))
        h = max(1, int(self.height()))
        proj = self.projectionMatrix((0, 0, w, h), self.getViewport())
        inv_mvp, ok = (proj * self.viewMatrix()).inverted()
        if not ok:
            return None

        x_ndc = (2.0 * sx / float(w)) - 1.0
        y_ndc = 1.0 - (2.0 * sy / float(h))
        near_h = inv_mvp.map(QVector4D(float(x_ndc), float(y_ndc), -1.0, 1.0))
        far_h = inv_mvp.map(QVector4D(float(x_ndc), float(y_ndc), 1.0, 1.0))
        if abs(float(near_h.w())) < 1e-12 or abs(float(far_h.w())) < 1e-12:
            return None

        near = np.array([near_h.x() / near_h.w(), near_h.y() / near_h.w(), near_h.z() / near_h.w()], dtype=np.float64)
        far = np.array([far_h.x() / far_h.w(), far_h.y() / far_h.w(), far_h.z() / far_h.w()], dtype=np.float64)
        d = far - near
        n = float(np.linalg.norm(d))
        if n < 1e-12:
            return None
        return near, d / n

    def _raycast_face(self, sx: float, sy: float, face_indices: np.ndarray | None = None) -> int | None:
        if self._pick_tri_a is None or self._pick_e1 is None or self._pick_e2 is None or self.pick_faces is None:
            return None
        ray = self._screen_ray(sx, sy)
        if ray is None:
            return None
        origin, direction = ray

        if face_indices is None:
            a = self._pick_tri_a
            e1 = self._pick_e1
            e2 = self._pick_e2
        else:
            if len(face_indices) == 0:
                return None
            a = self._pick_tri_a[face_indices]
            e1 = self._pick_e1[face_indices]
            e2 = self._pick_e2[face_indices]

        eps = 1e-9
        pvec = np.cross(np.broadcast_to(direction, a.shape), e2)
        det = np.einsum("ij,ij->i", e1, pvec)
        valid = np.abs(det) > eps
        if not np.any(valid):
            return None

        inv_det = np.zeros_like(det)
        inv_det[valid] = 1.0 / det[valid]
        tvec = origin - a
        u = np.einsum("ij,ij->i", tvec, pvec) * inv_det
        valid &= (u >= 0.0) & (u <= 1.0)
        if not np.any(valid):
            return None

        qvec = np.cross(tvec, e1)
        v = np.einsum("ij,j->i", qvec, direction) * inv_det
        valid &= (v >= 0.0) & ((u + v) <= 1.0)
        if not np.any(valid):
            return None

        t = np.einsum("ij,ij->i", e2, qvec) * inv_det
        valid &= t > eps
        if not np.any(valid):
            return None

        cand = np.where(valid)[0]
        nearest_local = int(cand[int(np.argmin(t[cand]))])
        if face_indices is None:
            return nearest_local
        return int(face_indices[nearest_local])

    def _ensure_selection_topology(self) -> None:
        if self.vertices is None or self.pick_faces is None:
            return
        if (
            self._face_normals is not None
            and self._face_adjacency is not None
            and self._pick_cache_token == (len(self.vertices), len(self.pick_faces))
        ):
            return

        tri = self.vertices[self.pick_faces]
        normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        lens = np.linalg.norm(normals, axis=1)
        lens = np.where(lens < 1e-12, 1e-12, lens)
        self._face_normals = normals / lens[:, None]

        edge_to_faces: Dict[Tuple[int, int], List[int]] = {}
        for fi, (a, b, c) in enumerate(self.pick_faces):
            for u, v in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
                e = (u, v) if u < v else (v, u)
                edge_to_faces.setdefault(e, []).append(fi)

        adj = [set() for _ in range(len(self.pick_faces))]
        for fs in edge_to_faces.values():
            if len(fs) < 2:
                continue
            for i in range(len(fs)):
                for j in range(i + 1, len(fs)):
                    adj[fs[i]].add(fs[j])
                    adj[fs[j]].add(fs[i])
        self._face_adjacency = [sorted(list(n)) for n in adj]
        self._pick_cache_token = (len(self.vertices), len(self.pick_faces))

    def smart_select(self, seed_face: int, angle_limit_deg: float = 30.0) -> Set[int]:
        self._ensure_selection_topology()
        if self._face_normals is None or self._face_adjacency is None:
            return {seed_face}
        cos_thresh = math.cos(math.radians(angle_limit_deg))
        selected: Set[int] = set()
        visited: Set[int] = {int(seed_face)}
        q = deque([int(seed_face)])
        while q:
            face = q.popleft()
            selected.add(face)
            n0 = self._face_normals[face]
            for nb in self._face_adjacency[face]:
                if nb in visited:
                    continue
                visited.add(nb)
                if float(np.dot(n0, self._face_normals[nb])) >= cos_thresh:
                    q.append(nb)
        return selected
