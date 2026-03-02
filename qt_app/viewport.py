from __future__ import annotations

from collections import deque
import math
from typing import Dict, List, Sequence, Set, Tuple

import numpy as np
from OpenGL import GL as ogl
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders as gl_shaders
from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QSize, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient, QVector3D, QVector4D, QRegion
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget
import trimesh
from qt_app import edge_selection
from ui.icon_loader import IconRegistry, load_icon_svg_file
from ui.theme import tokens


def _rgb255(color_hex: str) -> Tuple[int, int, int]:
    return tokens.hex_to_rgb255(color_hex)


def _rgba255(color_hex: str, alpha: float) -> Tuple[int, int, int, int]:
    r, g, b = _rgb255(color_hex)
    a = max(0, min(255, int(round(alpha * 255.0))))
    return (r, g, b, a)


class _CadHeadlightShaderProgram(gl_shaders.ShaderProgram):
    """Camera-attached headlight shader for GLMeshItem faces.

    This is the Python/pyqtgraph equivalent of the C++ "shader uniform" path in
    `ui-enhance-v2.md`: camera position is extracted from the inverted view
    matrix each frame and pushed into the mesh shader before drawing.
    """

    def __init__(self) -> None:
        super().__init__(
            "cad_headlight",
            [
                gl_shaders.VertexShader(
                    """
                    uniform mat4 u_mvp;
                    uniform mat4 u_view;
                    uniform mat3 u_normal;
                    attribute vec4 a_position;
                    attribute vec3 a_normal;
                    attribute vec4 a_color;
                    varying vec4 v_color;
                    varying vec3 v_normal;
                    varying vec3 v_pos_eye;
                    void main() {
                        vec4 pos_eye = u_view * a_position;
                        v_pos_eye = pos_eye.xyz;
                        v_normal = normalize(u_normal * a_normal);
                        v_color = a_color;
                        gl_Position = u_mvp * a_position;
                    }
                    """
                ),
                gl_shaders.FragmentShader(
                    """
                    #ifdef GL_ES
                    precision mediump float;
                    #endif
                    uniform vec3 lightPos;  // passed for parity with C++ headlight snippet
                    uniform vec3 viewPos;   // passed for parity with C++ headlight snippet
                    varying vec4 v_color;
                    varying vec3 v_normal;
                    varying vec3 v_pos_eye;
                    void main() {
                        vec3 N = normalize(v_normal);
                        vec3 V = normalize(-v_pos_eye);
                        vec3 L = V; // headlight attached to camera (eye origin in view space)
                        float diff = max(dot(N, L), 0.0);
                        // CAD-like two-tone / matcap-ish readability: hemisphere ambient + rim
                        // keeps topology visible without fully realistic lighting.
                        float hemi = clamp(0.5 + 0.5 * N.z, 0.0, 1.0);
                        vec3 skyTint = vec3(0.84, 0.90, 0.98);
                        vec3 groundTint = vec3(0.18, 0.21, 0.26);
                        vec3 hemiAmbient = mix(groundTint, skyTint, hemi);
                        float rim = pow(clamp(1.0 - max(dot(N, V), 0.0), 0.0, 1.0), 2.4);
                        float spec = 0.0;
                        if (diff > 0.0) {
                            vec3 H = normalize(L + V);
                            spec = pow(max(dot(N, H), 0.0), 18.0) * 0.22;
                        }
                        // `lightPos` / `viewPos` are uploaded every frame. Keep a tiny no-op
                        // dependency so the uniforms are not trivially optimized in some drivers.
                        float uniformKeepAlive = 1.0 + 0.0 * length(lightPos - viewPos);
                        float tone = 0.22 + 0.55 * diff + 0.08 * step(0.35, diff);
                        vec3 rgb = (v_color.rgb * tone + hemiAmbient * 0.12 + vec3(rim * 0.14) + vec3(spec)) * uniformKeepAlive;
                        gl_FragColor = vec4(rgb, v_color.a);
                    }
                    """
                ),
            ],
        )
        self._camera_world = np.zeros((3,), dtype=np.float32)
        self._view_matrix = np.identity(4, dtype=np.float32).reshape(-1)

    def set_camera_state(self, camera_world: np.ndarray, view_matrix) -> None:
        cam = np.asarray(camera_world, dtype=np.float32).reshape(3)
        self._camera_world = cam.copy()
        self._view_matrix = np.array(view_matrix.data(), dtype=np.float32)

    def __enter__(self):
        handle = super().__enter__()
        try:
            program = self.program()
            if program == -1:
                return handle

            if (loc := ogl.glGetUniformLocation(program, b"u_view")) != -1:
                ogl.glUniformMatrix4fv(loc, 1, False, self._view_matrix)

            cx, cy, cz = map(float, self._camera_world.tolist())
            if (loc := ogl.glGetUniformLocation(program, b"lightPos")) != -1:
                ogl.glUniform3f(loc, cx, cy, cz)
            if (loc := ogl.glGetUniformLocation(program, b"viewPos")) != -1:
                ogl.glUniform3f(loc, cx, cy, cz)
        except Exception:
            # If a driver drops an optional uniform, keep rendering.
            pass
        return handle


class OrbitDragButton(QToolButton):
    dragStarted = Signal(QPointF)
    dragMoved = Signal(QPointF)
    dragFinished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dragging = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._opacity_fx = QGraphicsOpacityEffect(self)
        self._opacity_fx.setOpacity(0.3)
        self.setGraphicsEffect(self._opacity_fx)
        self._opacity_anim = QVariantAnimation(self)
        self._opacity_anim.setDuration(140)
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._opacity_anim.valueChanged.connect(self._on_opacity_step)

    def _on_opacity_step(self, value) -> None:
        self._opacity_fx.setOpacity(float(value))

    def _animate_opacity(self, target: float) -> None:
        end = max(0.0, min(1.0, float(target)))
        self._opacity_anim.stop()
        self._opacity_anim.setStartValue(float(self._opacity_fx.opacity()))
        self._opacity_anim.setEndValue(end)
        self._opacity_anim.start()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_opacity(1.0)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging:
            self._animate_opacity(0.3)
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        side = min(self.width(), self.height())
        region = QRegion(0, 0, side, side, QRegion.RegionType.Ellipse)
        self.setMask(region)
        super().resizeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._animate_opacity(1.0)
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
            self._animate_opacity(1.0 if self.underMouse() else 0.3)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _CadMeshItem(gl.GLMeshItem):
    def __init__(
        self,
        *args,
        polygon_offset_fill: bool = False,
        polygon_offset_line: bool = False,
        wire_line_width: float | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._polygon_offset_fill = bool(polygon_offset_fill)
        self._polygon_offset_line = bool(polygon_offset_line)
        self._wire_line_width = None if wire_line_width is None else float(wire_line_width)

    def set_wire_line_width(self, width: float | None) -> None:
        self._wire_line_width = None if width is None else float(width)
        self.update()

    def paint(self) -> None:
        fill_offset_enabled = False
        line_offset_enabled = False
        line_width_overridden = False
        try:
            ogl.glDisable(ogl.GL_LIGHTING)
            ogl.glDisable(ogl.GL_COLOR_MATERIAL)
            ogl.glEnable(ogl.GL_DEPTH_TEST)
        except Exception:
            pass
        try:
            if self._polygon_offset_fill:
                ogl.glEnable(ogl.GL_POLYGON_OFFSET_FILL)
                ogl.glPolygonOffset(1.0, 1.0)
                fill_offset_enabled = True
            if self._polygon_offset_line:
                ogl.glEnable(ogl.GL_POLYGON_OFFSET_LINE)
                ogl.glPolygonOffset(-1.0, -1.0)
                line_offset_enabled = True
            if self._wire_line_width is not None and bool(self.opts.get("drawEdges")):
                ogl.glLineWidth(self._wire_line_width)
                line_width_overridden = True
        except Exception:
            pass
        try:
            super().paint()
        finally:
            try:
                if line_width_overridden:
                    ogl.glLineWidth(1.0)
                if line_offset_enabled:
                    ogl.glDisable(ogl.GL_POLYGON_OFFSET_LINE)
                if fill_offset_enabled:
                    ogl.glDisable(ogl.GL_POLYGON_OFFSET_FILL)
            except Exception:
                pass


class ThreeDViewportWidget(gl.GLViewWidget):
    cameraChanged = Signal(float, float)
    facesSelected = Signal(list)
    modelDropped = Signal(str)
    flattenRequested = Signal()
    splitToggleRequested = Signal()
    seamStateChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        # Use euler mode for a CAD-style Z-up orbit with no accumulated roll.
        super().__init__(parent, rotationMethod="euler")
        self.setObjectName("ThreeDViewportWidget")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setAutoFillBackground(False)
        self.setMinimumSize(100, 100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._viewport_theme = "light"
        self._vp_bg_color = tokens.VP_BG
        self._grid_minor_color = tokens.GRID_MINOR
        self._grid_major_color = tokens.GRID_MAJOR
        self._grid_minor_alpha = 0.62
        self._grid_major_alpha = 0.90
        self._mesh_diffuse_color = tokens.MESH_DIFFUSE
        self._edge_color = tokens.EDGE
        self._apply_viewport_palette(self._viewport_theme)
        self.setBackgroundColor(_rgba255(self._vp_bg_color, 1.0))
        self.setStyleSheet(
            """
            QOpenGLWidget#ThreeDViewportWidget {
                outline: none;
            }
            """
        )

        self.vertices: np.ndarray | None = None
        self.vertices32: np.ndarray | None = None
        self.render_faces: np.ndarray | None = None
        self.render_faces32: np.ndarray | None = None
        self.pick_faces: np.ndarray | None = None
        self.mesh_name = ""
        self.model_type = "mesh"
        self._brep_tri_face_id: np.ndarray | None = None
        self._brep_face_boundary_edge_ids: Dict[int, List[int]] = {}
        self._brep_edge_polylines: Dict[int, np.ndarray] = {}

        self.selection_mode = "single"
        self.selected_faces: Set[int] = set()
        self._hover_face: int | None = None
        self._isolate_mode = False
        self._isolated_pick_indices: Set[int] = set()
        self._active_edge_pick: Tuple[int, int] | None = None
        self._hover_edge: Tuple[int, int] | None = None
        self.anchor_edge: Tuple[int, int] | None = None
        self.cut_edges: Set[Tuple[int, int]] = set()
        self._hover_brep_chain: Tuple[int, ...] | None = None
        self._active_brep_chain: Tuple[int, ...] | None = None
        self._hover_brep_edge_id: int | None = None
        self._active_brep_edge_id: int | None = None
        self._anchor_brep_chain: Tuple[int, ...] | None = None
        self._cut_brep_chains: Set[Tuple[int, ...]] = set()
        self._brep_boundary_edge_ids: Set[int] = set()
        self._brep_boundary_chains: List[Tuple[int, ...]] = []
        self._brep_edge_to_chain: Dict[int, Tuple[int, ...]] = {}
        self._brep_edge_to_mesh_edges: Dict[int, List[Tuple[int, int]]] = {}
        self._brep_cut_display_edges: List[Tuple[int, int]] = []
        self._brep_anchor_display_edge: Tuple[int, int] | None = None
        self._brep_display_edge_to_chain: Dict[Tuple[int, int], Tuple[int, ...]] = {}
        self._brep_pick_mode = "edge"
        self._seam_candidate_edges: List[Tuple[int, int]] = []
        self._seam_boundary_edge_set: Set[Tuple[int, int]] = set()
        self._seam_pick_strategy = "triangle"
        self._seam_pick_px_tol = 10.0
        self._seam_feature_angle_deg = 42.0
        self._seam_screen_pick_edge_cap = 24000
        self._feature_edge_cache_token: Tuple[int, int, float] | None = None
        self._feature_edges_global: List[Tuple[int, int]] = []

        self._drag_start: Tuple[float, float] | None = None
        self._left_dragging = False
        self._left_press_modifiers = Qt.KeyboardModifier.NoModifier
        self._left_press_forwarded = False
        self._click_drag_threshold_px = 8.0
        self._nav_last: Tuple[float, float] | None = None
        self._active_nav_mode: str | None = None
        self.is_rotating = False
        self.is_panning = False
        self.is_zooming = False

        self.orbit_mode_enabled = False
        self.pan_mode_enabled = False
        self.zoom_mode_enabled = False
        self.technical_mode_enabled = False
        self.show_edges_enabled = True
        self.wireframe_enabled = False
        self.grid_visible = True
        self._camera_up: Tuple[float, float, float] | None = None
        self._accent_rgb = np.asarray(tokens.hex_to_rgbf(tokens.ACCENT), dtype=np.float32)

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
        self._render_mesh_is_volume = False
        self._headlight_shader = _CadHeadlightShaderProgram()
        self._orbit_sensitivity = 0.65
        self._orbit_sensitivity_fine = 0.35
        self._model_turntable_enabled = True
        self._model_yaw_deg = 0.0
        self._model_pitch_deg = 0.0

        self._pending_hover_pos: Tuple[float, float] | None = None
        self._mesh_center = np.zeros(3, dtype=np.float64)
        self._floating_orbit_last_pos: QPointF | None = None

        self.grid_minor_item = gl.GLGridItem(color=_rgba255(self._grid_minor_color, self._grid_minor_alpha))
        self.grid_minor_item.setSize(x=12000.0, y=12000.0, z=1.0)
        self.grid_minor_item.setSpacing(10.0, 10.0, 1.0)
        self.grid_minor_item.setVisible(self.grid_visible)
        self.addItem(self.grid_minor_item)

        self.grid_major_item = gl.GLGridItem(color=_rgba255(self._grid_major_color, self._grid_major_alpha))
        self.grid_major_item.setSize(x=12000.0, y=12000.0, z=1.0)
        self.grid_major_item.setSpacing(50.0, 50.0, 1.0)
        self.grid_major_item.setVisible(self.grid_visible)
        self.addItem(self.grid_major_item)

        self.mesh_item = _CadMeshItem(
            drawFaces=True,
            drawEdges=False,
            smooth=True,
            shader=self._headlight_shader,
            polygon_offset_fill=True,
        )
        self.mesh_item.opts["smooth"] = True
        self.mesh_item.opts["color"] = (*tokens.hex_to_rgbf(self._mesh_diffuse_color), 1.0)
        self.mesh_item.setGLOptions("opaque")
        self.mesh_item.setDepthValue(0)
        self.addItem(self.mesh_item)

        self.wire_item = _CadMeshItem(
            drawFaces=False,
            drawEdges=True,
            smooth=False,
            shader=None,
            polygon_offset_line=True,
            wire_line_width=1.2,
        )
        self.wire_item.opts["edgeColor"] = (*tokens.hex_to_rgbf(self._edge_color), 0.30)
        self.wire_item.setGLOptions("translucent")
        self.wire_item.setDepthValue(1)
        self.addItem(self.wire_item)

        self.selection_item = _CadMeshItem(
            drawFaces=True,
            drawEdges=False,
            smooth=True,
            shader=self._headlight_shader,
            glOptions="translucent",
        )
        self.selection_item.setDepthValue(2)
        self.selection_item.setVisible(False)
        self.addItem(self.selection_item)

        self.hover_edge_item = None
        self.anchor_edge_item = None
        self.cut_edges_item = None
        try:
            self.hover_edge_item = gl.GLLinePlotItem(
                pos=np.empty((0, 3), dtype=np.float32),
                color=(0.16, 0.80, 0.95, 0.98),
                width=4.0,
                antialias=True,
                mode="lines",
            )
            self.hover_edge_item.setGLOptions("translucent")
            self.hover_edge_item.setDepthValue(3)
            self.hover_edge_item.setVisible(False)
            self.addItem(self.hover_edge_item)

            self.anchor_edge_item = gl.GLLinePlotItem(
                pos=np.empty((0, 3), dtype=np.float32),
                color=(0.12, 0.86, 0.26, 0.95),
                width=3.0,
                antialias=True,
                mode="lines",
            )
            self.anchor_edge_item.setGLOptions("translucent")
            self.anchor_edge_item.setDepthValue(3)
            self.anchor_edge_item.setVisible(False)
            self.addItem(self.anchor_edge_item)

            self.cut_edges_item = gl.GLLinePlotItem(
                pos=np.empty((0, 3), dtype=np.float32),
                color=(0.93, 0.18, 0.14, 0.95),
                width=2.5,
                antialias=True,
                mode="lines",
            )
            self.cut_edges_item.setGLOptions("translucent")
            self.cut_edges_item.setDepthValue(3)
            self.cut_edges_item.setVisible(False)
            self.addItem(self.cut_edges_item)
        except Exception:
            self.hover_edge_item = None
            self.anchor_edge_item = None
            self.cut_edges_item = None

        self.overlay = QLabel("Drop 3D Model Here\n(STL / OBJ / STEP)", self)
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.setStyleSheet(
            f"QLabel {{ color:{tokens.BORDER}; font-size:24px; font-weight:{tokens.FONT_WEIGHT_SEMIBOLD}; background:transparent; }}"
        )
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.dim_label = QLabel("", self)
        self.dim_label.setStyleSheet(
            f"QLabel {{ color:{tokens.TEXT_PRIMARY}; background-color:{tokens.rgba(tokens.BG_PANEL, 0.86)}; border:1px solid {tokens.BORDER}; padding:{tokens.SPACE_XS}px {tokens.SPACE_S}px; }}"
        )
        self.dim_label.move(tokens.SPACE_M, tokens.SPACE_M)
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
            vp_r, vp_g, vp_b = tokens.hex_to_rgbf(self._vp_bg_color)
            ogl.glClearColor(vp_r, vp_g, vp_b, 1.0)
            ogl.glEnable(ogl.GL_DEPTH_TEST)
            self._prepare_shader_pipeline_state()
        except Exception:
            pass

    def paintGL(self) -> None:  # noqa: N802
        self._prepare_shader_pipeline_state()
        try:
            # Hard-refactor viewport cleanup:
            # dark theme wireframes are thicker, and face fill keeps polygon offset enabled
            # so edge lines remain visible over shaded triangles.
            target_wire_width = 2.5 if self._viewport_theme == "dark" else 1.2
            if getattr(self.wire_item, "_wire_line_width", None) != target_wire_width:
                self.wire_item.set_wire_line_width(target_wire_width)
            if hasattr(self.mesh_item, "_polygon_offset_fill") and not bool(getattr(self.mesh_item, "_polygon_offset_fill")):
                self.mesh_item._polygon_offset_fill = True
        except Exception:
            pass
        self._update_headlight_uniform_state()
        super().paintGL()
        self._prepare_shader_pipeline_state()
        self._update_floating_orbit_button_position()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        # A subtle post-pass gradient/vignette improves depth perception in dark mode.
        try:
            self._paint_soft_background_gradient()
        except Exception:
            pass

    def _prepare_shader_pipeline_state(self) -> None:
        try:
            ogl.glDisable(ogl.GL_LIGHTING)
            ogl.glDisable(ogl.GL_LIGHT0)
            ogl.glDisable(ogl.GL_COLOR_MATERIAL)
            ogl.glDisable(ogl.GL_NORMALIZE)
        except Exception:
            pass

    def _reset_model_display_rotation(self) -> None:
        self._model_yaw_deg = 0.0
        self._model_pitch_deg = 0.0
        self._apply_model_display_transform()

    def _model_rotation_matrix(self) -> np.ndarray:
        yaw = math.radians(float(self._model_yaw_deg))
        pitch = math.radians(float(self._model_pitch_deg))
        cz = math.cos(yaw)
        sz = math.sin(yaw)
        cx = math.cos(pitch)
        sx = math.sin(pitch)
        r_yaw = np.array(
            [
                [cz, -sz, 0.0],
                [sz, cz, 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        r_pitch = np.array(
            [
                [1.0, 0.0, 0.0],
                [0.0, cx, -sx],
                [0.0, sx, cx],
            ],
            dtype=np.float64,
        )
        return r_pitch @ r_yaw

    def _apply_model_display_transform(self) -> None:
        cx, cy, cz = map(float, self._mesh_center.tolist())
        yaw = float(self._model_yaw_deg)
        pitch = float(self._model_pitch_deg)
        for item in (self.mesh_item, self.wire_item, self.selection_item, self.hover_edge_item, self.cut_edges_item, self.anchor_edge_item):
            if item is None:
                continue
            try:
                item.resetTransform()
                if abs(yaw) < 1e-9 and abs(pitch) < 1e-9:
                    continue
                # Final transform = T(center) * R(pitch) * R(yaw) * T(-center)
                item.translate(-cx, -cy, -cz, local=False)
                if abs(yaw) >= 1e-9:
                    item.rotate(yaw, 0.0, 0.0, 1.0, local=False)
                if abs(pitch) >= 1e-9:
                    item.rotate(pitch, 1.0, 0.0, 0.0, local=False)
                item.translate(cx, cy, cz, local=False)
            except Exception:
                pass

    def _orbit_model_by_delta(self, dx: float, dy: float, modifiers: Qt.KeyboardModifiers) -> None:
        sens = self._orbit_sensitivity_fine if (modifiers & Qt.KeyboardModifier.ShiftModifier) else self._orbit_sensitivity
        self._model_yaw_deg = float((self._model_yaw_deg - (dx * sens)) % 360.0)
        self._model_pitch_deg = float(np.clip(self._model_pitch_deg + (dy * sens), -85.0, 85.0))
        self._apply_model_display_transform()
        self.update()

    def _update_headlight_uniform_state(self) -> None:
        # Modern OpenGL / shader path (ui-enhance-v2.md): derive camera world
        # position from the inverted view matrix and upload as light/view uniforms.
        try:
            view_matrix = self.viewMatrix()
            inv_view, ok = view_matrix.inverted()
            if not ok:
                return
            cam = inv_view.column(3).toVector3D()
            self._headlight_shader.set_camera_state(
                np.array([float(cam.x()), float(cam.y()), float(cam.z())], dtype=np.float32),
                view_matrix,
            )
        except Exception:
            pass

    def _paint_soft_background_gradient(self) -> None:
        if self.width() < 2 or self.height() < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        h = float(max(1, self.height()))
        w = float(max(1, self.width()))
        if self._viewport_theme == "dark":
            top = QColor("#2C2C2C")
            mid = QColor("#22262C")
            bot = QColor("#1A1A1A")
            top.setAlpha(42)
            mid.setAlpha(14)
            bot.setAlpha(70)
        else:
            top = QColor("#F6F8FB")
            mid = QColor("#EEF2F7")
            bot = QColor("#E4EAF2")
            top.setAlpha(28)
            mid.setAlpha(10)
            bot.setAlpha(36)

        gradient = QLinearGradient(0.0, 0.0, 0.0, h)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(0.55, mid)
        gradient.setColorAt(1.0, bot)
        painter.fillRect(self.rect(), gradient)

        # Center lift + edge vignette to separate mesh silhouette from the background.
        cx = w * 0.5
        cy = h * 0.46
        r = max(w, h) * 0.85
        center_glow = QRadialGradient(cx, cy, r)
        glow_col = QColor("#6EA8FF" if self._viewport_theme == "dark" else "#B8D6FF")
        glow_col.setAlpha(22 if self._viewport_theme == "dark" else 16)
        edge_col = QColor(0, 0, 0, 0)
        center_glow.setColorAt(0.0, glow_col)
        center_glow.setColorAt(0.65, QColor(0, 0, 0, 0))
        center_glow.setColorAt(1.0, edge_col)
        painter.fillRect(self.rect(), center_glow)

        vignette = QRadialGradient(w * 0.5, h * 0.52, max(w, h) * 0.95)
        vignette.setColorAt(0.60, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 42 if self._viewport_theme == "dark" else 24))
        painter.fillRect(self.rect(), vignette)
        painter.end()

    def _update_phase3_viewport_render_params(self) -> None:
        # Phase 3 adaptive wireframe visibility + stronger grid contrast.
        if self._viewport_theme == "dark":
            self._grid_minor_alpha = 0.62
            self._grid_major_alpha = 0.92
            self.wire_item.set_wire_line_width(2.5)
        else:
            self._grid_minor_alpha = 0.62
            self._grid_major_alpha = 0.90
            self.wire_item.set_wire_line_width(1.2)

    def _apply_viewport_palette(self, theme: str) -> None:
        if theme == "dark":
            self._vp_bg_color = tokens.BG_MAIN
            self._grid_minor_color = tokens.BG_HOVER
            self._grid_major_color = tokens.BORDER
            self._mesh_diffuse_color = tokens.TEXT_SECONDARY
            self._edge_color = tokens.EDGE
            self._grid_minor_alpha = 0.62
            self._grid_major_alpha = 0.92
            return
        self._vp_bg_color = tokens.VP_BG
        # Phase 3 contrast override: keep token direction, but darken the effective
        # grid colors for better spatial orientation on the light industrial viewport.
        self._grid_minor_color = "#C6CDD6"
        self._grid_major_color = "#A7B0BB"
        self._mesh_diffuse_color = tokens.MESH_DIFFUSE
        self._edge_color = tokens.EDGE
        self._grid_minor_alpha = 0.62
        self._grid_major_alpha = 0.90

    def viewport_theme(self) -> str:
        return self._viewport_theme

    def set_viewport_theme(self, theme: str) -> None:
        normalized = str(theme).strip().lower()
        if normalized not in {"light", "dark"}:
            normalized = "light"
        self._viewport_theme = normalized
        self._apply_viewport_palette(normalized)
        self._update_phase3_viewport_render_params()
        self.setBackgroundColor(_rgba255(self._vp_bg_color, 1.0))
        if self.isValid():
            try:
                self.makeCurrent()
                vp_r, vp_g, vp_b = tokens.hex_to_rgbf(self._vp_bg_color)
                ogl.glClearColor(vp_r, vp_g, vp_b, 1.0)
                self.doneCurrent()
            except Exception:
                pass

        self._base_render_face_colors = self._build_source_face_colors()
        if self._base_render_face_colors is None:
            self._base_render_face_colors = self._build_default_face_colors()
        self._update_grid_extent()
        self._update_mesh_visuals()
        self.update()

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
        self._left_press_modifiers = event.modifiers()
        self._left_press_forwarded = False
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

        # Preserve drag navigation in the base widget while keeping click-selection custom.
        if event.button() == Qt.MouseButton.LeftButton:
            self._left_press_forwarded = True
            super().mousePressEvent(event)
            return

        if event.button() == Qt.MouseButton.RightButton:
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
            if self._model_turntable_enabled and self.vertices is not None:
                self._orbit_model_by_delta(dx, dy, event.modifiers())
            else:
                sens = self._orbit_sensitivity_fine if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else self._orbit_sensitivity
                self.orbit(-dx * sens, dy * sens)
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
            if (ddx * ddx + ddy * ddy) > (self._click_drag_threshold_px * self._click_drag_threshold_px):
                self._left_dragging = True
                if self._left_press_forwarded:
                    super().mouseMoveEvent(event)
                    return
            event.accept()
            return

        # Free hover feedback when no buttons are pressed.
        if event.buttons() == Qt.MouseButton.NoButton:
            if self.selection_mode == "cut":
                self._update_hovered_edge(cur[0], cur[1])
            else:
                self._schedule_hover_pick(cur[0], cur[1])
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        # Keep orbit pivot anchored to the model bounding-box center.
        # Double-click no longer re-centers the camera to a picked face centroid.
        super().mouseDoubleClickEvent(event)

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
                if self._left_dragging:
                    if self._left_press_forwarded:
                        super().mouseReleaseEvent(event)
                    else:
                        event.accept()
                    return

                if self.selection_mode == "cut":
                    if self.vertices is None or self.pick_faces is None:
                        event.accept()
                        return
                    sx = float(event.position().x())
                    sy = float(event.position().y())
                    self._update_hovered_edge(sx, sy)
                    mods = self._left_press_modifiers
                    if self.model_type == "brep":
                        chain = self._hover_brep_chain
                        if chain is None:
                            event.accept()
                            return
                        if bool(mods & Qt.KeyboardModifier.ShiftModifier):
                            self._set_brep_anchor_chain(chain)
                        else:
                            action, _ = self._toggle_brep_cut_chain(chain)
                            if action == "anchor_conflict":
                                event.accept()
                                return
                    else:
                        edge = self._hover_edge
                        if edge is None:
                            event.accept()
                            return
                        self._active_edge_pick = edge
                        if bool(mods & Qt.KeyboardModifier.ShiftModifier):
                            self.anchor_edge = self._normalized_edge(edge)
                            if self.anchor_edge in self.cut_edges:
                                self.cut_edges.discard(self.anchor_edge)
                        else:
                            normalized = self._normalized_edge(edge)
                            if self.anchor_edge is not None and normalized == self.anchor_edge:
                                event.accept()
                                return
                            if normalized in self.cut_edges:
                                self.cut_edges.discard(normalized)
                            else:
                                self.cut_edges.add(normalized)
                    self._update_seam_overlays()
                    self._emit_seam_state_changed()
                    event.accept()
                    return

                if self.selection_mode == "off" or self.vertices is None or self.pick_faces is None:
                    event.accept()
                    return
                hit = self._raycast_face(float(event.position().x()), float(event.position().y()))
                mods = self._left_press_modifiers
                ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
                alt = bool(mods & Qt.KeyboardModifier.AltModifier)
                if hit is None:
                    if not ctrl and not alt:
                        self.selected_faces.clear()
                        self._recompute_seam_candidates()
                        self._update_mesh_visuals()
                        self.facesSelected.emit(self.get_selected_faces())
                        self._emit_seam_state_changed()
                    event.accept()
                    return

                new_faces = self._selection_units_from_pick_hit(int(hit))
                if alt:
                    self.selected_faces.difference_update(new_faces)
                elif ctrl:
                    self.selected_faces.update(new_faces)
                else:
                    self.selected_faces = set(new_faces)

                if self._isolate_mode and self._isolated_pick_indices:
                    self._isolated_pick_indices = set(self._selected_pick_face_indices().tolist())

                self._recompute_seam_candidates()
                self._update_mesh_visuals()
                self.facesSelected.emit(self.get_selected_faces())
                self._emit_seam_state_changed()
                event.accept()
                return
            finally:
                self._drag_start = None
                self._left_dragging = False
                self._left_press_forwarded = False
                self._left_press_modifiers = Qt.KeyboardModifier.NoModifier

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
                if (
                    p.endswith(".stl")
                    or p.endswith(".obj")
                    or p.endswith(".stp")
                    or p.endswith(".step")
                    or p.endswith(".iges")
                    or p.endswith(".igs")
                ):
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
        self.hud.setObjectName("HUDContainer")
        self.hud.setStyleSheet(
            f"""
            QWidget#HUDContainer {{
                background: transparent;
                border: none;
            }}
            QToolButton#hudGhostButton {{
                min-width:36px;
                min-height:36px;
                max-width:36px;
                max-height:36px;
                color:{tokens.TEXT_PRIMARY};
                background: transparent;
                border: none;
                border-radius:{tokens.RADIUS_1}px;
                padding:0px;
            }}
            QToolButton#hudGhostButton:hover {{
                background-color:{tokens.rgba(tokens.BG_PANEL, 0.32)};
            }}
            QToolButton#hudGhostButton:checked {{
                background-color:{tokens.rgba(tokens.BG_PANEL, 0.42)};
            }}
            QToolButton#hudGhostButton:pressed {{
                background-color:{tokens.rgba(tokens.BG_PANEL, 0.50)};
            }}
            QToolButton#hudOrbitButton {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QToolButton#hudOrbitButton:hover {{
                background: transparent;
                border: none;
            }}
            QToolButton#hudOrbitButton:pressed, QToolButton#hudOrbitButton:checked {{
                background: transparent;
                border: none;
            }}
            """
        )
        hud_layout = QHBoxLayout(self.hud)
        hud_layout.setContentsMargins(0, 0, 0, 0)
        hud_layout.setSpacing(tokens.SPACE_XS)

        def apply_hud_icon(button: QToolButton, icon_name: str, *, size_px: int, color: str = tokens.TEXT_PRIMARY) -> None:
            icon = IconRegistry.get_icon(icon_name, size=size_px, color=color)
            if icon.isNull():
                return
            button.setIcon(icon)
            button.setIconSize(QSize(size_px, size_px))

        def make_ghost_button(*, tooltip: str, icon_name: str, checkable: bool = False) -> QToolButton:
            btn = QToolButton(self.hud)
            btn.setObjectName("hudGhostButton")
            btn.setText("")
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            btn.setFixedSize(36, 36)
            btn.setCheckable(checkable)
            btn.setToolTip(tooltip)
            apply_hud_icon(btn, icon_name, size_px=20)
            return btn

        self.hud_fit_btn = make_ghost_button(tooltip="Zoom Fit", icon_name="frame_selection")
        self.hud_fit_btn.clicked.connect(self.reset_camera)

        # Keep the pan/zoom override toggles for compatibility with existing methods,
        # but remove them from the visible HUD to avoid ambiguous glyph buttons.
        self.hud_pan_btn = QToolButton(self.hud)
        self.hud_pan_btn.setText("")
        self.hud_pan_btn.setCheckable(True)
        self.hud_pan_btn.setToolTip("Pan Override")
        self.hud_pan_btn.toggled.connect(self._toggle_pan_mode)
        self.hud_pan_btn.hide()

        self.hud_zoom_btn = QToolButton(self.hud)
        self.hud_zoom_btn.setText("")
        self.hud_zoom_btn.setCheckable(True)
        self.hud_zoom_btn.setToolTip("Zoom Override")
        self.hud_zoom_btn.toggled.connect(self._toggle_zoom_mode)
        self.hud_zoom_btn.hide()

        self.hud_orbit_btn = QToolButton(self.hud)
        self.hud_orbit_btn.setObjectName("hudOrbitButton")
        self.hud_orbit_btn.setText("")
        self.hud_orbit_btn.setToolTip("Orbit Override")
        self.hud_orbit_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.hud_orbit_btn.setCheckable(True)
        self.hud_orbit_btn.setChecked(False)
        self.hud_orbit_btn.setFixedSize(48, 48)
        self.hud_orbit_btn.setIconSize(QSize(32, 32))
        self.hud_orbit_btn.toggled.connect(self._toggle_orbit_mode)
        # PH2-VP-S5: use the industrial SVG file icon directly (no Base64 HUD orbit path).
        orbit_icon = load_icon_svg_file("ui/icons/Industrial_SVG_Set_v1/orbit.svg", size=32, color=tokens.TEXT_PRIMARY)
        if not orbit_icon.isNull():
            self.hud_orbit_btn.setIcon(orbit_icon)

        self.hud_split_btn = make_ghost_button(tooltip="Toggle 2D Preview", icon_name="isolate")
        self.hud_split_btn.clicked.connect(self.splitToggleRequested.emit)

        hud_layout.addWidget(self.hud_fit_btn)
        hud_layout.addWidget(self.hud_orbit_btn)
        hud_layout.addWidget(self.hud_split_btn)
        self.hud.adjustSize()
        self.hud.show()

        self.floating_orbit_btn = OrbitDragButton(self)
        self.floating_orbit_btn.setObjectName("FloatingOrbitButton")
        self.floating_orbit_btn.setText("")
        self.floating_orbit_btn.setToolTip("Drag to Orbit Around Model")
        self.floating_orbit_btn.setFixedSize(48, 48)
        self.floating_orbit_btn.setStyleSheet(
            f"""
            QToolButton#FloatingOrbitButton {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QToolButton#FloatingOrbitButton:hover {{
                background: transparent;
                border: none;
            }}
            QToolButton#FloatingOrbitButton:pressed {{
                background: transparent;
                border: none;
            }}
            """
        )
        self.floating_orbit_btn.setIconSize(QSize(32, 32))
        # Keep the floating orbit drag button on the same file-based icon source.
        floating_orbit_icon = load_icon_svg_file("ui/icons/Industrial_SVG_Set_v1/orbit.svg", size=32, color=tokens.ACCENT)
        if not floating_orbit_icon.isNull():
            self.floating_orbit_btn.setIcon(floating_orbit_icon)
        self.floating_orbit_btn.dragStarted.connect(self._on_floating_orbit_drag_started)
        self.floating_orbit_btn.dragMoved.connect(self._on_floating_orbit_drag_moved)
        self.floating_orbit_btn.dragFinished.connect(self._on_floating_orbit_drag_finished)
        self.floating_orbit_btn.hide()
        self._position_hud()

    def _position_hud(self) -> None:
        margin = 10
        self.hud.adjustSize()
        self.hud.move(max(0, self.width() - self.hud.width() - margin), max(0, self.height() - self.hud.height() - margin))
        self.hud.raise_()
        if hasattr(self, "floating_orbit_btn"):
            self.floating_orbit_btn.raise_()
        self.dim_label.raise_()

    def _on_floating_orbit_drag_started(self, global_pos: QPointF) -> None:
        self._floating_orbit_last_pos = QPointF(global_pos)

    def _on_floating_orbit_drag_moved(self, global_pos: QPointF) -> None:
        if self._floating_orbit_last_pos is None:
            self._floating_orbit_last_pos = QPointF(global_pos)
            return
        dx = float(global_pos.x() - self._floating_orbit_last_pos.x())
        dy = float(global_pos.y() - self._floating_orbit_last_pos.y())
        self._floating_orbit_last_pos = QPointF(global_pos)
        if self._model_turntable_enabled and self.vertices is not None:
            self._orbit_model_by_delta(dx, dy, Qt.KeyboardModifier.NoModifier)
        else:
            self.orbit(-dx * self._orbit_sensitivity, dy * self._orbit_sensitivity)
        self._on_camera_event()

    def _on_floating_orbit_drag_finished(self) -> None:
        self._floating_orbit_last_pos = None
        self.floating_orbit_btn.setCursor(Qt.CursorShape.SizeAllCursor)
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
        if self._floating_orbit_last_pos is not None:
            return

        center = self.opts.get("center", QVector3D(float(self._mesh_center[0]), float(self._mesh_center[1]), float(self._mesh_center[2])))
        anchor = self.mapFrom3D(center)
        btn = self.floating_orbit_btn
        margin = tokens.SPACE_S
        x = anchor.x() - (btn.width() // 2)
        y = anchor.y() - (btn.height() // 2)
        x = max(margin, min(self.width() - btn.width() - margin, x))
        y = max(margin, min(self.height() - btn.height() - margin, y))
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

    def _bbox_center(self, vertices: np.ndarray) -> np.ndarray:
        verts = np.asarray(vertices, dtype=np.float64)
        if verts.ndim != 2 or verts.shape[1] != 3 or len(verts) == 0:
            return np.zeros(3, dtype=np.float64)
        return (verts.min(axis=0) + verts.max(axis=0)) * 0.5

    def clear_view(self) -> None:
        self.model_type = "mesh"
        self._brep_tri_face_id = None
        self._brep_face_boundary_edge_ids = {}
        self._brep_edge_polylines = {}
        self.vertices = None
        self.vertices32 = None
        self.render_faces = None
        self.render_faces32 = None
        self.pick_faces = None
        self.selected_faces.clear()
        self._hover_face = None
        self._isolate_mode = False
        self._isolated_pick_indices.clear()
        self._active_edge_pick = None
        self._hover_edge = None
        self.anchor_edge = None
        self.cut_edges.clear()
        self._hover_brep_chain = None
        self._active_brep_chain = None
        self._hover_brep_edge_id = None
        self._active_brep_edge_id = None
        self._anchor_brep_chain = None
        self._cut_brep_chains.clear()
        self._brep_boundary_edge_ids.clear()
        self._brep_boundary_chains = []
        self._brep_edge_to_chain = {}
        self._brep_edge_to_mesh_edges = {}
        self._brep_cut_display_edges = []
        self._brep_anchor_display_edge = None
        self._brep_display_edge_to_chain = {}
        self._seam_candidate_edges = []
        self._seam_boundary_edge_set.clear()
        self._seam_pick_strategy = "triangle"
        self._feature_edge_cache_token = None
        self._feature_edges_global = []

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
        self._render_mesh_is_volume = False
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
        self.mesh_item.opts["color"] = (*tokens.hex_to_rgbf(self._mesh_diffuse_color), 1.0)
        self.wire_item.setMeshData(
            vertexes=np.empty((0, 3), dtype=np.float32),
            faces=np.empty((0, 3), dtype=np.int32),
            drawFaces=False,
            drawEdges=True,
            edgeColor=(*tokens.hex_to_rgbf(self._edge_color), 0.30),
        )
        self.wire_item.opts["edgeColor"] = (*tokens.hex_to_rgbf(self._edge_color), 0.30)
        self.selection_item.setVisible(False)
        for item in (self.hover_edge_item, self.anchor_edge_item, self.cut_edges_item):
            if item is None:
                continue
            item.setData(pos=np.empty((0, 3), dtype=np.float32))
            item.setVisible(False)
        self._reset_model_display_rotation()

        self.setCameraPosition(pos=QVector3D(0.0, 0.0, 0.0), distance=600.0, elevation=24.0, azimuth=-58.0)
        self.opts["fov"] = 45.0
        self._camera_up = (0.0, 0.0, 1.0)
        self._update_grid_extent()
        self.overlay.show()
        self.dim_label.setText("")
        self.dim_label.hide()
        self.floating_orbit_btn.hide()
        self._emit_seam_state_changed()
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
        brep_metadata: Dict | None = None,
    ) -> None:
        self.mesh_name = name
        self.model_type = "brep" if isinstance(brep_metadata, dict) and brep_metadata else "mesh"
        self._brep_tri_face_id = None
        self._brep_face_boundary_edge_ids = {}
        self._brep_edge_polylines = {}
        if self.model_type == "brep":
            tri_face = np.asarray(brep_metadata.get("tri_face_id", np.empty((0,), dtype=np.int64)), dtype=np.int64)
            if tri_face.ndim == 1:
                self._brep_tri_face_id = tri_face
            self._brep_face_boundary_edge_ids = {
                int(k): [int(x) for x in (vals or [])]
                for k, vals in dict(brep_metadata.get("face_boundary_edge_ids", {})).items()
            }
            self._brep_edge_polylines = {
                int(k): np.asarray(v, dtype=np.float64)
                for k, v in dict(brep_metadata.get("edge_polylines", {})).items()
            }
        self.vertices = np.asarray(vertices, dtype=np.float64)
        self._mesh_center = self._bbox_center(self.vertices)
        self.vertices32 = np.ascontiguousarray(self.vertices.astype(np.float32, copy=False))
        raw_render_faces = np.asarray(render_faces, dtype=np.int64)
        self.render_faces = self._fix_render_face_winding(raw_render_faces)
        self.render_faces32 = np.ascontiguousarray(self.render_faces.astype(np.int32, copy=False))
        self.pick_faces = np.asarray(pick_faces, dtype=np.int64) if pick_faces is not None else self.render_faces

        self.selected_faces.clear()
        self._hover_face = None
        self._isolate_mode = False
        self._isolated_pick_indices.clear()
        self._active_edge_pick = None
        self._hover_edge = None
        self.anchor_edge = None
        self.cut_edges.clear()
        self._hover_brep_chain = None
        self._active_brep_chain = None
        self._hover_brep_edge_id = None
        self._active_brep_edge_id = None
        self._anchor_brep_chain = None
        self._cut_brep_chains.clear()
        self._brep_boundary_edge_ids.clear()
        self._brep_boundary_chains = []
        self._brep_edge_to_chain = {}
        self._brep_edge_to_mesh_edges = {}
        self._brep_cut_display_edges = []
        self._brep_anchor_display_edge = None
        self._brep_display_edge_to_chain = {}
        self._seam_candidate_edges = []
        self._seam_boundary_edge_set.clear()
        self._seam_pick_strategy = "triangle"
        self._feature_edge_cache_token = None
        self._feature_edges_global = []
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
        self._build_brep_edge_mesh_mapping()
        self._recompute_seam_candidates()
        self._update_mesh_visuals()
        self._update_seam_overlays()
        self._reset_model_display_rotation()
        self._fit_camera_to_mesh()
        self._update_grid_extent()

        lx, ly, lz = dims_mm
        self.dim_label.setText(f"{name} | LxWxH: {lx:.1f} x {ly:.1f} x {lz:.1f} mm")
        self.dim_label.show()
        self.overlay.hide()
        self._emit_seam_state_changed()
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
        center = self._bbox_center(self.vertices)
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
            self._reset_model_display_rotation()
            self._fit_camera_to_mesh()
        else:
            self.clear_view()
        self._on_camera_event()

    def apply_view_preset(self, preset: str) -> None:
        if self.vertices is None:
            return
        mins = self.vertices.min(axis=0)
        maxs = self.vertices.max(axis=0)
        center = self._bbox_center(self.vertices)
        self._mesh_center = center
        dist = max(float(np.max(maxs - mins)) * 2.2, 20.0)

        mapping = {
            "FRONT": (0.0, -90.0, (0.0, 0.0, 1.0)),
            "BACK": (0.0, 90.0, (0.0, 0.0, 1.0)),
            "LEFT": (0.0, 180.0, (0.0, 0.0, 1.0)),
            "RIGHT": (0.0, 0.0, (0.0, 0.0, 1.0)),
            "TOP": (90.0, 0.0, (0.0, 1.0, 0.0)),
            "BOTTOM": (-90.0, 0.0, (0.0, -1.0, 0.0)),
        }
        if preset not in mapping:
            return

        elev, azim, up = mapping[preset]

        self.setCameraPosition(
            pos=QVector3D(float(center[0]), float(center[1]), float(center[2])),
            distance=dist,
            elevation=elev,
            azimuth=azim,
        )
        self.opts["fov"] = 40.0
        self._camera_up = up
        self.update()
        self._on_camera_event()

    def set_selection_mode(self, mode: str) -> None:
        self.selection_mode = mode
        if self.selection_mode != "cut":
            self._hover_brep_chain = None
            self._hover_brep_edge_id = None
            if self._hover_edge is not None:
                self._hover_edge = None
                self._update_seam_overlays()
                self._emit_seam_state_changed()
        else:
            self._recompute_seam_candidates()
            self._update_seam_overlays()
            self._emit_seam_state_changed()

    def set_brep_pick_mode(self, mode: str) -> None:
        normalized = str(mode).strip().lower()
        if normalized not in {"edge", "chain"}:
            normalized = "edge"
        if normalized == self._brep_pick_mode:
            return
        self._brep_pick_mode = normalized
        self._hover_brep_chain = None
        self._active_brep_chain = None
        self._hover_brep_edge_id = None
        self._active_brep_edge_id = None
        self._active_edge_pick = None
        self._recompute_seam_candidates()
        self._update_seam_overlays()
        self._emit_seam_state_changed()

    def clear_selection(self) -> None:
        if not self.selected_faces:
            return
        self.selected_faces.clear()
        if self._isolate_mode:
            self._isolated_pick_indices.clear()
            self._isolate_mode = False
        self._recompute_seam_candidates()
        self._update_mesh_visuals()
        self.facesSelected.emit([])
        self._emit_seam_state_changed()

    def invert_selection(self) -> None:
        self._invert_selection()

    def get_active_edge_pick(self) -> Tuple[int, int] | None:
        return self._hover_edge if self._hover_edge is not None else self._active_edge_pick

    def get_anchor_edge(self) -> Tuple[int, int] | None:
        return self.anchor_edge

    def get_cut_edges(self) -> List[Tuple[int, int]]:
        return sorted(self.cut_edges)

    def set_anchor_from_active_edge(self) -> Tuple[int, int] | None:
        if self.model_type == "brep":
            chain = self._hover_brep_chain or self._active_brep_chain
            if chain is None:
                return None
            edge = self._set_brep_anchor_chain(chain)
            self._update_seam_overlays()
            self._emit_seam_state_changed()
            return edge if edge is not None else (-1, -1)
        edge_for_action = self._edge_for_actions()
        if edge_for_action is None:
            return None
        self.anchor_edge = self._normalized_edge(edge_for_action)
        self._active_edge_pick = self.anchor_edge
        if self.anchor_edge in self.cut_edges:
            self.cut_edges.discard(self.anchor_edge)
        self._update_seam_overlays()
        self._emit_seam_state_changed()
        return self.anchor_edge

    def toggle_cut_from_active_edge(self) -> Tuple[str, Tuple[int, int]] | None:
        if self.model_type == "brep":
            chain = self._hover_brep_chain or self._active_brep_chain
            if chain is None:
                return None
            action, edge = self._toggle_brep_cut_chain(chain)
            if edge is None:
                edge = (-1, -1)
            self._update_seam_overlays()
            self._emit_seam_state_changed()
            return (action, edge)
        edge_for_action = self._edge_for_actions()
        if edge_for_action is None:
            return None
        edge = self._normalized_edge(edge_for_action)
        self._active_edge_pick = edge
        if self.anchor_edge is not None and edge == self.anchor_edge:
            return ("anchor_conflict", edge)
        if edge in self.cut_edges:
            self.cut_edges.discard(edge)
            action = "removed"
        else:
            self.cut_edges.add(edge)
            action = "added"
        self._update_seam_overlays()
        self._emit_seam_state_changed()
        return (action, edge)

    def clear_cut_edges(self) -> None:
        if self.model_type == "brep":
            changed = bool(self._cut_brep_chains) or (self._anchor_brep_chain is not None) or (self._active_brep_chain is not None)
            self._cut_brep_chains.clear()
            self._anchor_brep_chain = None
            self._active_brep_chain = None
            self._hover_brep_chain = None
            self._active_brep_edge_id = None
            self._hover_brep_edge_id = None
            self.cut_edges.clear()
            self.anchor_edge = None
            self._active_edge_pick = None
            self._brep_cut_display_edges = []
            self._brep_anchor_display_edge = None
            self._brep_display_edge_to_chain = {}
            self._update_seam_overlays()
            if changed:
                self._emit_seam_state_changed()
            return
        changed = bool(self.cut_edges) or (self.anchor_edge is not None) or (self._active_edge_pick is not None)
        self.cut_edges.clear()
        self.anchor_edge = None
        self._active_edge_pick = None
        self._update_seam_overlays()
        if changed:
            self._emit_seam_state_changed()

    def clear_seam_state(self) -> None:
        self.clear_cut_edges()

    def remove_cut_edge(self, edge: Sequence[int]) -> Tuple[int, int] | None:
        if self.model_type == "brep":
            normalized = self._normalized_edge(edge)
            chain = self._brep_display_edge_to_chain.get(normalized)
            if chain is None or chain not in self._cut_brep_chains:
                return None
            self._cut_brep_chains.discard(chain)
            self._sync_brep_chain_edge_state()
            self._update_seam_overlays()
            self._emit_seam_state_changed()
            return normalized
        normalized = self._normalized_edge(edge)
        if normalized not in self.cut_edges:
            return None
        self.cut_edges.discard(normalized)
        self._update_seam_overlays()
        self._emit_seam_state_changed()
        return normalized

    def auto_guess_anchor_edge(self) -> Tuple[int, int] | None:
        if self.vertices is None or self.pick_faces is None:
            return None
        if not self.selected_faces:
            return None
        if self.model_type == "brep":
            self._recompute_seam_candidates()
            if not self._brep_boundary_chains:
                return None
            best_chain = None
            best_len = -1.0
            for chain in self._brep_boundary_chains:
                try:
                    length = edge_selection.chain_length_from_polylines(chain, self._brep_edge_polylines)
                except Exception:
                    length = 0.0
                if length > best_len:
                    best_len = length
                    best_chain = chain
            if best_chain is None:
                return None
            edge = self._set_brep_anchor_chain(best_chain)
            self._update_seam_overlays()
            self._emit_seam_state_changed()
            return edge if edge is not None else (-1, -1)
        self._recompute_seam_candidates()
        candidates = sorted(self._seam_boundary_edge_set) if self._seam_boundary_edge_set else sorted(set(self._seam_candidate_edges))
        if not candidates:
            return None
        arr = np.asarray(candidates, dtype=np.int64)
        lengths = np.linalg.norm(self.vertices[arr[:, 0]] - self.vertices[arr[:, 1]], axis=1)
        best_idx = int(np.argmax(lengths))
        best = self._normalized_edge(arr[best_idx])
        self.anchor_edge = best
        if best in self.cut_edges:
            self.cut_edges.discard(best)
        self._active_edge_pick = best
        self._update_seam_overlays()
        self._emit_seam_state_changed()
        return best

    def set_isolate_mode(self, enabled: bool) -> None:
        if bool(enabled):
            if not self.selected_faces:
                self._isolate_mode = False
                self._isolated_pick_indices.clear()
            else:
                self._isolate_mode = True
                self._isolated_pick_indices = set(self._selected_pick_face_indices().tolist())
        else:
            self._isolate_mode = False
            self._isolated_pick_indices.clear()
        self._update_mesh_visuals()

    def is_isolate_mode(self) -> bool:
        return bool(self._isolate_mode)

    def set_technical_mode(self, enabled: bool) -> None:
        self.technical_mode_enabled = bool(enabled)
        self._update_mesh_visuals()

    def set_edges_visible(self, enabled: bool) -> None:
        self.show_edges_enabled = bool(enabled)
        self._update_mesh_visuals()

    def set_wireframe_mode(self, enabled: bool) -> None:
        self.wireframe_enabled = bool(enabled)
        if self.wireframe_enabled:
            self.show_edges_enabled = True
        self._update_mesh_visuals()

    def set_grid_visible(self, enabled: bool) -> None:
        self.grid_visible = bool(enabled)
        try:
            self.grid_minor_item.setVisible(self.grid_visible)
            self.grid_major_item.setVisible(self.grid_visible)
        except Exception:
            pass
        self.update()

    def get_selected_faces(self) -> List[int]:
        return sorted(self.selected_faces)

    def _brep_selection_enabled(self) -> bool:
        return (
            self.model_type == "brep"
            and self.pick_faces is not None
            and self._brep_tri_face_id is not None
            and len(self._brep_tri_face_id) == len(self.pick_faces)
        )

    def _selected_pick_face_indices(self) -> np.ndarray:
        if self.pick_faces is None or not self.selected_faces:
            return np.empty((0,), dtype=np.int64)
        if self._brep_selection_enabled():
            selected_ids = np.asarray(sorted(self.selected_faces), dtype=np.int64)
            return np.nonzero(np.isin(self._brep_tri_face_id, selected_ids))[0].astype(np.int64, copy=False)
        idx = np.asarray(sorted(self.selected_faces), dtype=np.int64)
        return idx[(idx >= 0) & (idx < len(self.pick_faces))]

    def _selection_units_from_pick_hit(self, hit: int) -> Set[int]:
        if self._brep_selection_enabled():
            face_id = int(self._brep_tri_face_id[int(hit)])
            return {face_id} if face_id >= 0 else set()
        if self.selection_mode == "single":
            return {int(hit)}
        return self.smart_select(int(hit), 30.0)

    def _selected_units_all(self) -> Set[int]:
        if self.pick_faces is None:
            return set()
        if self._brep_selection_enabled():
            ids = np.asarray(self._brep_tri_face_id, dtype=np.int64)
            ids = ids[ids >= 0]
            return set(int(x) for x in np.unique(ids).tolist())
        return set(range(len(self.pick_faces)))

    def _is_pick_face_selected(self, pick_face_index: int) -> bool:
        idx = int(pick_face_index)
        if idx < 0:
            return False
        if self._brep_selection_enabled():
            if idx >= len(self._brep_tri_face_id):
                return False
            return int(self._brep_tri_face_id[idx]) in self.selected_faces
        return idx in self.selected_faces

    def _build_brep_edge_mesh_mapping(self) -> None:
        self._brep_edge_to_mesh_edges = {}
        if not self._brep_selection_enabled() or self.vertices is None or self.pick_faces is None:
            return
        if not self._brep_edge_polylines:
            return

        mesh_edges = self._all_unique_mesh_edges()
        if not mesh_edges:
            return
        mesh_edge_set = set(mesh_edges)

        verts = np.asarray(self.vertices, dtype=np.float64)
        nearest_fn = None
        try:
            from scipy.spatial import cKDTree  # type: ignore

            tree = cKDTree(verts)

            def _nearest(points: np.ndarray) -> np.ndarray:
                _, idx = tree.query(points, k=1)
                return np.asarray(idx, dtype=np.int64)

            nearest_fn = _nearest
        except Exception:
            nearest_fn = None

        for edge_id, polyline in self._brep_edge_polylines.items():
            arr = np.asarray(polyline, dtype=np.float64)
            if arr.ndim != 2 or arr.shape[1] != 3 or len(arr) < 2:
                self._brep_edge_to_mesh_edges[int(edge_id)] = []
                continue

            if nearest_fn is not None:
                nearest_idx = nearest_fn(arr)
            else:
                nearest_idx_list: List[int] = []
                for p in arr:
                    d2 = np.sum((verts - p[None, :]) ** 2, axis=1)
                    nearest_idx_list.append(int(np.argmin(d2)))
                nearest_idx = np.asarray(nearest_idx_list, dtype=np.int64)

            mapped_edges: List[Tuple[int, int]] = []
            for i in range(len(nearest_idx) - 1):
                a = int(nearest_idx[i])
                b = int(nearest_idx[i + 1])
                if a == b:
                    continue
                e = self._normalized_edge((a, b))
                if e in mesh_edge_set:
                    mapped_edges.append(e)
            if not mapped_edges and len(nearest_idx) >= 2:
                e = self._normalized_edge((int(nearest_idx[0]), int(nearest_idx[-1])))
                if e in mesh_edge_set:
                    mapped_edges.append(e)
            self._brep_edge_to_mesh_edges[int(edge_id)] = sorted(set(mapped_edges))

    def _brep_chain_mesh_edges(self, chain: Sequence[int]) -> List[Tuple[int, int]]:
        out: set[Tuple[int, int]] = set()
        for edge_id in chain:
            for e in self._brep_edge_to_mesh_edges.get(int(edge_id), []):
                out.add(self._normalized_edge(e))
        return sorted(out)

    def _brep_chain_representative_edge(self, chain: Sequence[int]) -> Tuple[int, int] | None:
        mesh_edges = self._brep_chain_mesh_edges(chain)
        if mesh_edges:
            return mesh_edges[0]
        return None

    def _sync_brep_chain_edge_state(self) -> None:
        if self.model_type != "brep":
            return
        self.cut_edges.clear()
        self._brep_cut_display_edges = []
        self._brep_anchor_display_edge = None
        self._brep_display_edge_to_chain = {}

        if self._anchor_brep_chain is not None:
            anchor_rep = self._brep_chain_representative_edge(self._anchor_brep_chain)
            self.anchor_edge = anchor_rep
            self._brep_anchor_display_edge = anchor_rep
            if anchor_rep is not None:
                self._brep_display_edge_to_chain[self._normalized_edge(anchor_rep)] = tuple(self._anchor_brep_chain)
        else:
            self.anchor_edge = None

        for chain in sorted(self._cut_brep_chains):
            mesh_edges = self._brep_chain_mesh_edges(chain)
            for e in mesh_edges:
                self.cut_edges.add(self._normalized_edge(e))
            rep = self._brep_chain_representative_edge(chain)
            if rep is not None:
                nr = self._normalized_edge(rep)
                self._brep_cut_display_edges.append(nr)
                self._brep_display_edge_to_chain[nr] = tuple(chain)
        self._brep_cut_display_edges = sorted(set(self._brep_cut_display_edges))

    def _set_brep_anchor_chain(self, chain: Sequence[int]) -> Tuple[int, int] | None:
        normalized_chain = tuple(int(x) for x in chain)
        if not normalized_chain:
            return None
        self._anchor_brep_chain = normalized_chain
        self._cut_brep_chains.discard(normalized_chain)
        self._sync_brep_chain_edge_state()
        if self._brep_anchor_display_edge is not None:
            self._active_edge_pick = self._brep_anchor_display_edge
        self._active_brep_chain = normalized_chain
        return self._brep_anchor_display_edge

    def _toggle_brep_cut_chain(self, chain: Sequence[int]) -> Tuple[str, Tuple[int, int] | None]:
        normalized_chain = tuple(int(x) for x in chain)
        if not normalized_chain:
            return ("ignored", None)
        if self._anchor_brep_chain is not None and tuple(self._anchor_brep_chain) == normalized_chain:
            rep = self._brep_chain_representative_edge(normalized_chain)
            return ("anchor_conflict", rep)
        if normalized_chain in self._cut_brep_chains:
            self._cut_brep_chains.discard(normalized_chain)
            action = "removed"
        else:
            self._cut_brep_chains.add(normalized_chain)
            action = "added"
        self._sync_brep_chain_edge_state()
        rep = self._brep_chain_representative_edge(normalized_chain)
        if rep is not None:
            self._active_edge_pick = rep
        self._active_brep_chain = normalized_chain
        return (action, rep)

    def _on_camera_event(self) -> None:
        self._camera_debounce.start()
        self._update_floating_orbit_button_position()

    def _emit_seam_state_changed(self) -> None:
        if self.model_type == "brep":
            anchor_payload = None if self._brep_anchor_display_edge is None else tuple(self._brep_anchor_display_edge)
            cut_payload = [tuple(e) for e in sorted(self._brep_cut_display_edges)]
            active_edge = self._hover_edge if self._hover_edge is not None else self._active_edge_pick
            active_payload = None if active_edge is None else tuple(active_edge)
        else:
            anchor_payload = None if self.anchor_edge is None else tuple(self.anchor_edge)
            cut_payload = [tuple(e) for e in sorted(self.cut_edges)]
            active_edge = self._active_edge_pick
            active_payload = None if active_edge is None else tuple(active_edge)
        self.seamStateChanged.emit(
            {
                "model_type": self.model_type,
                "brep_pick_mode": self._brep_pick_mode,
                "active_edge": active_payload,
                "hover_edge": None if self._hover_edge is None else tuple(self._hover_edge),
                "anchor_edge": anchor_payload,
                "cut_edges": cut_payload,
                "cut_chain_count": len(self._cut_brep_chains) if self.model_type == "brep" else len(self.cut_edges),
                "boundary_edges": [tuple(e) for e in sorted(self._seam_boundary_edge_set)],
                "pick_strategy": self._seam_pick_strategy,
            }
        )

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
            idx = self._selected_pick_face_indices()
            if len(idx):
                used_vertices = np.unique(self.pick_faces[idx].reshape(-1))
                verts = self.vertices[used_vertices]
            else:
                verts = self.vertices
        else:
            verts = self.vertices

        mins = verts.min(axis=0)
        maxs = verts.max(axis=0)
        diag = float(np.linalg.norm(maxs - mins))
        dist = max(diag * 1.5, 1.0)
        center = self._bbox_center(self.vertices)
        self._mesh_center = center
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
        all_faces = self._selected_units_all()
        self.selected_faces = all_faces.difference(self.selected_faces)
        if self._isolate_mode:
            self._isolated_pick_indices = set(self._selected_pick_face_indices().tolist())
        self._recompute_seam_candidates()
        self._update_mesh_visuals()
        self.facesSelected.emit(self.get_selected_faces())
        self._emit_seam_state_changed()

    def _toggle_isolate(self) -> None:
        self.set_isolate_mode(not self._isolate_mode)

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

        minor_step = step
        major_step = max(50.0, step * 5.0)

        self.grid_minor_item.resetTransform()
        self.grid_minor_item.setSize(x=x_size, y=y_size, z=1.0)
        self.grid_minor_item.setSpacing(minor_step, minor_step, 1.0)
        self.grid_minor_item.setColor(_rgba255(self._grid_minor_color, float(self._grid_minor_alpha)))
        self.grid_minor_item.translate(cx, cy, 0.0)

        self.grid_major_item.resetTransform()
        self.grid_major_item.setSize(x=x_size, y=y_size, z=1.0)
        self.grid_major_item.setSpacing(major_step, major_step, 1.0)
        self.grid_major_item.setColor(_rgba255(self._grid_major_color, float(self._grid_major_alpha)))
        self.grid_major_item.translate(cx, cy, 0.1)

    def _fix_render_face_winding(self, faces: np.ndarray) -> np.ndarray:
        if self.vertices is None or faces.size == 0:
            return faces
        self._render_mesh_is_volume = False
        try:
            tri_mesh = trimesh.Trimesh(vertices=self.vertices, faces=faces, process=False)
            self._render_mesh_is_volume = bool(getattr(tri_mesh, "is_volume", False))
            if not self._render_mesh_is_volume:
                return faces
            volume = float(getattr(tri_mesh, "volume", 0.0))
            if np.isfinite(volume) and volume < 0.0:
                fixed_faces = faces.copy()
                fixed_faces[:, [1, 2]] = fixed_faces[:, [2, 1]]
                return fixed_faces
        except Exception:
            return faces
        return faces

    def _normalize_normals(self, normals: np.ndarray | None) -> np.ndarray | None:
        if normals is None or self.vertices is None:
            return None
        arr = np.asarray(normals, dtype=np.float64)
        if arr.shape != self.vertices.shape:
            return None
        lens = np.linalg.norm(arr, axis=1)
        lens = np.where(lens < 1e-12, 1.0, lens)
        arr = arr / lens[:, None]
        return arr

    def _invert_normals_if_needed(self, normals: np.ndarray | None) -> np.ndarray | None:
        if normals is None or self.vertices is None:
            return None
        if not self._render_mesh_is_volume:
            return normals
        radial = self.vertices - self._mesh_center[None, :]
        radial_len = np.linalg.norm(radial, axis=1)
        valid = radial_len > 1e-10
        if int(np.count_nonzero(valid)) < 16:
            return normals
        radial_dir = radial[valid] / radial_len[valid][:, None]
        score = float(np.mean(np.einsum("ij,ij->i", normals[valid], radial_dir)))
        if score < -0.20:
            return -normals
        return normals

    def _compute_vertex_normals_from_trimesh(self) -> np.ndarray | None:
        if self.vertices is None or self.render_faces is None:
            return None
        try:
            tri_mesh = trimesh.Trimesh(vertices=self.vertices, faces=self.render_faces, process=False)
            if bool(getattr(tri_mesh, "is_volume", False)):
                volume = float(getattr(tri_mesh, "volume", 0.0))
                if np.isfinite(volume) and volume < 0.0:
                    tri_mesh.invert()
            vn = self._normalize_normals(np.asarray(tri_mesh.vertex_normals, dtype=np.float64))
            vn = self._invert_normals_if_needed(vn)
            if vn is not None and len(vn) == len(self.vertices):
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
        vn = self._normalize_normals(vn)
        vn = self._invert_normals_if_needed(vn)
        return vn

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

        mesh_diffuse = np.array(tokens.hex_to_rgbf(self._mesh_diffuse_color), dtype=np.float32)
        base = np.tile(mesh_diffuse[None, :], (len(self.render_faces), 1)).astype(np.float32, copy=False)
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

        if self.technical_mode_enabled and len(colors):
            lum = colors[:, :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
            mono = np.clip(0.20 + 0.60 * lum, 0.0, 1.0)
            colors[:, :3] = mono[:, None]

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
                if ridx_hover >= 0 and not self._is_pick_face_selected(self._hover_face):
                    colors[ridx_hover] = np.array([self._accent_rgb[0], self._accent_rgb[1], self._accent_rgb[2], 0.55], dtype=np.float32)

        if self._pick_to_render is not None and self.selected_faces:
            idx = self._selected_pick_face_indices()
            ridx = self._pick_to_render[idx]
            ridx = ridx[ridx >= 0]
            if len(ridx):
                colors[ridx] = np.array([self._accent_rgb[0], self._accent_rgb[1], self._accent_rgb[2], 0.78], dtype=np.float32)

        vertex_colors = self._face_colors_to_vertex_colors(colors)

        self.mesh_item.setMeshData(
            vertexes=self.vertices32,
            faces=self.render_faces32,
            vertexColors=vertex_colors,
            smooth=True,
            drawEdges=False,
            shader=self._headlight_shader,
        )
        self.mesh_item.opts["smooth"] = True
        self.mesh_item.opts["color"] = (*tokens.hex_to_rgbf(self._mesh_diffuse_color), 1.0)
        self.mesh_item.setGLOptions("opaque")
        self.mesh_item.setVisible(not self.wireframe_enabled)
        self._apply_model_display_transform()

        wire_vertices = np.ascontiguousarray(self.vertices32, dtype=np.float32)
        edge_alpha = 0.35 if self.wireframe_enabled else 0.30
        edge_color = (*tokens.hex_to_rgbf(self._edge_color), edge_alpha)
        self.wire_item.setMeshData(
            vertexes=wire_vertices,
            faces=self.render_faces32,
            drawFaces=False,
            drawEdges=True,
            edgeColor=edge_color,
        )
        self.wire_item.opts["edgeColor"] = edge_color
        self.wire_item.setGLOptions("translucent")
        self.wire_item.setVisible(self.show_edges_enabled or self.wireframe_enabled)
        self._apply_model_display_transform()

        if self.selected_faces and self.pick_faces is not None and self.vertices32 is not None:
            idx = self._selected_pick_face_indices()
            if len(idx):
                sel_faces = np.ascontiguousarray(self.pick_faces[idx].astype(np.int32, copy=False))
                sel_colors = np.tile(
                    np.array([self._accent_rgb[0], self._accent_rgb[1], self._accent_rgb[2], 0.82], dtype=np.float32),
                    (len(sel_faces), 1),
                )
                self.selection_item.setMeshData(
                    vertexes=self.vertices32,
                    faces=sel_faces,
                    faceColors=sel_colors,
                    smooth=True,
                    drawEdges=False,
                    shader=self._headlight_shader,
                )
                self.selection_item.setVisible(True)
                self._apply_model_display_transform()
            else:
                self.selection_item.setVisible(False)
        else:
            self.selection_item.setVisible(False)

        self._update_seam_overlays()
        self.update()

    def _edge_segments_positions(self, edges: Sequence[Tuple[int, int]]) -> np.ndarray:
        if self.vertices32 is None or len(edges) == 0:
            return np.empty((0, 3), dtype=np.float32)
        n = len(self.vertices32)
        pts: List[np.ndarray] = []
        for a, b in sorted({self._normalized_edge(e) for e in edges}):
            if a < 0 or b < 0 or a >= n or b >= n or a == b:
                continue
            pts.append(self.vertices32[a])
            pts.append(self.vertices32[b])
        if not pts:
            return np.empty((0, 3), dtype=np.float32)
        return np.ascontiguousarray(np.vstack(pts).astype(np.float32, copy=False))

    def _chain_segments_positions(self, chains: Sequence[Tuple[int, ...]]) -> np.ndarray:
        if not chains:
            return np.empty((0, 3), dtype=np.float32)
        pts: List[np.ndarray] = []
        for chain in chains:
            for edge_id in chain:
                polyline = np.asarray(self._brep_edge_polylines.get(int(edge_id), np.empty((0, 3))), dtype=np.float64)
                if polyline.ndim != 2 or polyline.shape[1] != 3 or len(polyline) < 2:
                    continue
                for i in range(len(polyline) - 1):
                    a = np.asarray(polyline[i], dtype=np.float32)
                    b = np.asarray(polyline[i + 1], dtype=np.float32)
                    pts.append(a)
                    pts.append(b)
        if not pts:
            return np.empty((0, 3), dtype=np.float32)
        return np.ascontiguousarray(np.vstack(pts).astype(np.float32, copy=False))

    def _update_seam_overlays(self) -> None:
        if self.vertices32 is None:
            for item in (self.hover_edge_item, self.anchor_edge_item, self.cut_edges_item):
                if item is None:
                    continue
                item.setData(pos=np.empty((0, 3), dtype=np.float32))
                item.setVisible(False)
            return

        if self.model_type == "brep":
            hover_chains = [self._hover_brep_chain] if self._hover_brep_chain is not None else []
            anchor_chains = [self._anchor_brep_chain] if self._anchor_brep_chain is not None else []
            cut_chains = sorted(self._cut_brep_chains)
            hover_pos = self._chain_segments_positions([tuple(c) for c in hover_chains if c is not None])
            anchor_pos = self._chain_segments_positions([tuple(c) for c in anchor_chains if c is not None])
            cut_pos = self._chain_segments_positions([tuple(c) for c in cut_chains])
            if len(hover_pos) == 0 and self._hover_edge is not None:
                hover_pos = self._edge_segments_positions([self._hover_edge])
            if len(anchor_pos) == 0 and self.anchor_edge is not None:
                anchor_pos = self._edge_segments_positions([self.anchor_edge])
            if len(cut_pos) == 0 and self.cut_edges:
                cut_pos = self._edge_segments_positions(sorted(self.cut_edges))
        else:
            hover_pos = self._edge_segments_positions([self._hover_edge] if self._hover_edge is not None else [])
            anchor_pos = self._edge_segments_positions([self.anchor_edge] if self.anchor_edge is not None else [])
            cut_pos = self._edge_segments_positions(sorted(self.cut_edges))

        if self.hover_edge_item is not None:
            self.hover_edge_item.setData(pos=hover_pos, color=(0.16, 0.80, 0.95, 0.98))
            self.hover_edge_item.setVisible(len(hover_pos) >= 2)
        if self.anchor_edge_item is not None:
            self.anchor_edge_item.setData(pos=anchor_pos, color=(0.12, 0.86, 0.26, 0.95))
            self.anchor_edge_item.setVisible(len(anchor_pos) >= 2)
        if self.cut_edges_item is not None:
            self.cut_edges_item.setData(pos=cut_pos, color=(0.93, 0.18, 0.14, 0.95))
            self.cut_edges_item.setVisible(len(cut_pos) >= 2)
        self._apply_model_display_transform()

    def _edge_for_actions(self) -> Tuple[int, int] | None:
        if self.model_type == "brep":
            chain = self._hover_brep_chain or self._active_brep_chain
            if chain is not None:
                rep = self._brep_chain_representative_edge(chain)
                if rep is not None:
                    return self._normalized_edge(rep)
        if self._hover_edge is not None:
            return self._normalized_edge(self._hover_edge)
        if self._active_edge_pick is not None:
            return self._normalized_edge(self._active_edge_pick)
        return None

    def _display_vertices_for_projection(self) -> np.ndarray:
        if self.vertices is None:
            return np.empty((0, 3), dtype=np.float64)
        verts = np.asarray(self.vertices, dtype=np.float64)
        if not self._model_turntable_enabled:
            return verts
        if abs(self._model_yaw_deg) < 1e-9 and abs(self._model_pitch_deg) < 1e-9:
            return verts
        center = self._mesh_center.astype(np.float64, copy=False)
        rot = self._model_rotation_matrix()
        return center + ((verts - center[None, :]) @ rot.T)

    def _viewproj_matrix_np(self) -> np.ndarray | None:
        try:
            w = max(1, int(self.width()))
            h = max(1, int(self.height()))
            vp = self.projectionMatrix((0, 0, w, h), self.getViewport()) * self.viewMatrix()
            # Qt returns column-major data.
            return np.array(vp.data(), dtype=np.float64).reshape((4, 4), order="F")
        except Exception:
            return None

    def _all_unique_mesh_edges(self) -> List[Tuple[int, int]]:
        if self.pick_faces is None:
            return []
        faces = np.asarray(self.pick_faces, dtype=np.int64)
        if len(faces) == 0:
            return []
        edges = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
        return sorted({self._normalized_edge(e) for e in edges})

    def _feature_edges_cached(self) -> List[Tuple[int, int]]:
        if self.pick_faces is None or self.vertices is None:
            return []
        token = (int(len(self.vertices)), int(len(self.pick_faces)), float(self._seam_feature_angle_deg))
        if self._feature_edge_cache_token == token:
            return list(self._feature_edges_global)
        try:
            feature = edge_selection.compute_feature_edges(
                np.asarray(self.pick_faces, dtype=np.int64),
                np.asarray(self.vertices, dtype=np.float64),
                self._seam_feature_angle_deg,
            )
        except Exception:
            feature = []
        self._feature_edge_cache_token = token
        self._feature_edges_global = [self._normalized_edge(e) for e in feature]
        return list(self._feature_edges_global)

    def _recompute_seam_candidates(self) -> None:
        self._seam_candidate_edges = []
        self._seam_boundary_edge_set.clear()
        self._brep_boundary_edge_ids.clear()
        self._brep_boundary_chains = []
        self._brep_edge_to_chain = {}
        self._seam_pick_strategy = "triangle"

        if self.pick_faces is None or self.vertices is None:
            self._hover_edge = None
            self._hover_brep_chain = None
            self._hover_brep_edge_id = None
            return

        if self._brep_selection_enabled() and self.selected_faces:
            edge_counts: Dict[int, int] = {}
            for face_id in sorted(self.selected_faces):
                for edge_id in self._brep_face_boundary_edge_ids.get(int(face_id), []):
                    eid = int(edge_id)
                    edge_counts[eid] = edge_counts.get(eid, 0) + 1

            boundary_edge_ids = sorted([eid for eid, count in edge_counts.items() if count == 1])
            self._brep_boundary_edge_ids = set(boundary_edge_ids)
            try:
                chains = edge_selection.build_edge_chains(
                    boundary_edge_ids,
                    self._brep_edge_polylines,
                    tangent_thresh_deg=20.0,
                )
            except Exception:
                chains = []
            self._brep_boundary_chains = [tuple(int(x) for x in chain) for chain in chains if chain]
            edge_to_chain: Dict[int, Tuple[int, ...]] = {}
            for chain in self._brep_boundary_chains:
                for edge_id in chain:
                    edge_to_chain[int(edge_id)] = tuple(chain)
            self._brep_edge_to_chain = edge_to_chain

            valid_units: set[Tuple[int, ...]] = set(self._brep_boundary_chains)
            valid_units.update((int(eid),) for eid in boundary_edge_ids)
            if self._anchor_brep_chain is not None and tuple(self._anchor_brep_chain) not in valid_units:
                self._anchor_brep_chain = None
            self._cut_brep_chains = {tuple(ch) for ch in self._cut_brep_chains if tuple(ch) in valid_units}
            if self._hover_brep_chain is not None and tuple(self._hover_brep_chain) not in valid_units:
                self._hover_brep_chain = None
            if self._active_brep_chain is not None and tuple(self._active_brep_chain) not in valid_units:
                self._active_brep_chain = None
            if self._hover_brep_edge_id is not None and int(self._hover_brep_edge_id) not in self._brep_boundary_edge_ids:
                self._hover_brep_edge_id = None
            if self._active_brep_edge_id is not None and int(self._active_brep_edge_id) not in self._brep_boundary_edge_ids:
                self._active_brep_edge_id = None

            mesh_boundary_edges: set[Tuple[int, int]] = set()
            for edge_id in boundary_edge_ids:
                for e in self._brep_chain_mesh_edges((int(edge_id),)):
                    mesh_boundary_edges.add(self._normalized_edge(e))
            self._seam_boundary_edge_set = set(mesh_boundary_edges)
            self._seam_candidate_edges = sorted(mesh_boundary_edges)
            if self._brep_boundary_edge_ids:
                if self._brep_pick_mode == "chain" and self._brep_boundary_chains:
                    self._seam_pick_strategy = "brep-chain"
                else:
                    self._seam_pick_strategy = "brep-edge"
            else:
                self._seam_pick_strategy = "triangle"
            self._sync_brep_chain_edge_state()
            if self._hover_edge is not None and self._seam_candidate_edges:
                if self._hover_edge not in set(self._seam_candidate_edges):
                    self._hover_edge = None
            return

        # No active B-Rep face patch: clear chain state and use existing mesh heuristics.
        self._hover_brep_chain = None
        self._active_brep_chain = None
        self._hover_brep_edge_id = None
        self._active_brep_edge_id = None
        self._anchor_brep_chain = None
        self._cut_brep_chains.clear()
        self.cut_edges.clear()
        self.anchor_edge = None
        self._brep_cut_display_edges = []
        self._brep_anchor_display_edge = None
        self._brep_display_edge_to_chain = {}
        self._brep_edge_to_chain = {}

        selected_pick_idx = self._selected_pick_face_indices()
        if len(selected_pick_idx):
            sub = edge_selection.build_selected_submesh(self.pick_faces, selected_pick_idx)
            faces_sub = np.asarray(sub.get("faces_sub", np.empty((0, 3), dtype=np.int64)), dtype=np.int64)
            vmap = np.asarray(sub.get("vertex_ids_global", np.empty((0,), dtype=np.int64)), dtype=np.int64)
            boundary_local = edge_selection.compute_patch_boundary_edges(faces_sub)
            boundary_global: List[Tuple[int, int]] = []
            for a, b in boundary_local:
                if a < 0 or b < 0 or a >= len(vmap) or b >= len(vmap):
                    continue
                boundary_global.append(self._normalized_edge((vmap[a], vmap[b])))
            self._seam_boundary_edge_set = set(boundary_global)
            self._seam_candidate_edges = sorted(self._seam_boundary_edge_set)
            if self._seam_candidate_edges and len(self._seam_candidate_edges) <= self._seam_screen_pick_edge_cap:
                self._seam_pick_strategy = "screen"
            else:
                self._seam_pick_strategy = "triangle"
        else:
            feature_edges = self._feature_edges_cached()
            if feature_edges and len(feature_edges) <= self._seam_screen_pick_edge_cap:
                self._seam_candidate_edges = sorted(set(feature_edges))
                self._seam_pick_strategy = "screen"
            else:
                self._seam_candidate_edges = []
                self._seam_pick_strategy = "triangle"

        if self._hover_edge is not None:
            if self._seam_candidate_edges and self._hover_edge not in set(self._seam_candidate_edges):
                self._hover_edge = None
            elif self.pick_faces is None:
                self._hover_edge = None

    def _update_hovered_edge(self, sx: float, sy: float) -> None:
        if self.vertices is None or self.pick_faces is None:
            return
        prev = self._hover_edge
        prev_chain = self._hover_brep_chain
        hovered = None

        if self._seam_pick_strategy in {"brep-edge", "brep-chain"} and self._brep_boundary_edge_ids:
            viewproj = self._viewproj_matrix_np()
            if viewproj is not None:
                try:
                    picked_edge_id = edge_selection.screen_space_pick_polyline_edge(
                        mouse_xy=(sx, sy),
                        edge_ids=sorted(self._brep_boundary_edge_ids),
                        edge_polylines=self._brep_edge_polylines,
                        viewproj=viewproj,
                        viewport_w=int(self.width()),
                        viewport_h=int(self.height()),
                        px_tol=self._seam_pick_px_tol,
                    )
                except Exception:
                    picked_edge_id = None
                if picked_edge_id is not None:
                    edge_id = int(picked_edge_id)
                    self._hover_brep_edge_id = edge_id
                    self._active_brep_edge_id = edge_id
                    if self._seam_pick_strategy == "brep-chain":
                        norm_chain = tuple(self._brep_edge_to_chain.get(edge_id, (edge_id,)))
                    else:
                        norm_chain = (edge_id,)
                    self._hover_brep_chain = norm_chain
                    self._active_brep_chain = norm_chain
                    hovered = self._brep_chain_representative_edge(norm_chain)
                else:
                    self._hover_brep_edge_id = None
                    self._hover_brep_chain = None
        elif self._seam_pick_strategy == "screen" and self._seam_candidate_edges:
            viewproj = self._viewproj_matrix_np()
            if viewproj is not None:
                try:
                    hovered = edge_selection.screen_space_pick_edge(
                        mouse_xy=(sx, sy),
                        edges=self._seam_candidate_edges,
                        vertices=self._display_vertices_for_projection(),
                        viewproj=viewproj,
                        viewport_w=int(self.width()),
                        viewport_h=int(self.height()),
                        px_tol=self._seam_pick_px_tol,
                    )
                except Exception:
                    hovered = None

        if hovered is None:
            has_brep_boundary = bool(self.model_type == "brep" and self._brep_boundary_edge_ids)
            if not has_brep_boundary:
                hit = self._raycast_face_hit(sx, sy)
                if hit is not None:
                    face_id, hit_point = hit
                    candidate = self._nearest_edge_on_face(int(face_id), hit_point)
                    selected_pick_idx = self._selected_pick_face_indices()
                    if self._seam_boundary_edge_set and len(selected_pick_idx) > 0 and candidate not in self._seam_boundary_edge_set:
                        hovered = None
                    else:
                        hovered = candidate
            if self.model_type == "brep":
                self._hover_brep_edge_id = None
                self._hover_brep_chain = None

        self._hover_edge = None if hovered is None else self._normalized_edge(hovered)
        if self._hover_edge is not None:
            self._active_edge_pick = self._hover_edge
        if prev != self._hover_edge or prev_chain != self._hover_brep_chain:
            self._update_seam_overlays()
            self._emit_seam_state_changed()

    def _schedule_hover_pick(self, sx: float, sy: float) -> None:
        self._pending_hover_pos = (float(sx), float(sy))
        if not self._hover_timer.isActive():
            self._hover_timer.start()

    def _process_hover_pick(self) -> None:
        if self.selection_mode == "cut":
            return
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
        if self._model_turntable_enabled and (abs(self._model_yaw_deg) > 1e-9 or abs(self._model_pitch_deg) > 1e-9):
            r_inv = self._model_rotation_matrix().T
            center = self._mesh_center.astype(np.float64, copy=False)
            origin = center + (r_inv @ (origin - center))
            direction = r_inv @ direction
            dnorm = float(np.linalg.norm(direction))
            if dnorm > 1e-12:
                direction = direction / dnorm

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

    def _raycast_face_hit(self, sx: float, sy: float, face_indices: np.ndarray | None = None) -> Tuple[int, np.ndarray] | None:
        if self._pick_tri_a is None or self._pick_e1 is None or self._pick_e2 is None or self.pick_faces is None:
            return None
        ray = self._screen_ray(sx, sy)
        if ray is None:
            return None
        origin, direction = ray
        if self._model_turntable_enabled and (abs(self._model_yaw_deg) > 1e-9 or abs(self._model_pitch_deg) > 1e-9):
            r_inv = self._model_rotation_matrix().T
            center = self._mesh_center.astype(np.float64, copy=False)
            origin = center + (r_inv @ (origin - center))
            direction = r_inv @ direction
            dnorm = float(np.linalg.norm(direction))
            if dnorm > 1e-12:
                direction = direction / dnorm

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
        hit_face = nearest_local if face_indices is None else int(face_indices[nearest_local])
        hit_point = a[nearest_local] + (u[nearest_local] * e1[nearest_local]) + (v[nearest_local] * e2[nearest_local])
        return int(hit_face), np.asarray(hit_point, dtype=np.float64)

    @staticmethod
    def _normalized_edge(edge: Sequence[int]) -> Tuple[int, int]:
        a = int(edge[0])
        b = int(edge[1])
        return (a, b) if a < b else (b, a)

    @staticmethod
    def _distance_sq_point_segment(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
        ab = b - a
        denom = float(np.dot(ab, ab))
        if denom <= 1e-18:
            d = p - a
            return float(np.dot(d, d))
        t = float(np.dot(p - a, ab) / denom)
        t = max(0.0, min(1.0, t))
        q = a + t * ab
        d = p - q
        return float(np.dot(d, d))

    def _nearest_edge_on_face(self, face_id: int, hit_point: np.ndarray) -> Tuple[int, int]:
        if self.pick_faces is None or self.vertices is None:
            raise ValueError("No mesh loaded.")
        tri = self.pick_faces[int(face_id)]
        ids = [int(tri[0]), int(tri[1]), int(tri[2])]
        pts = [self.vertices[ids[0]], self.vertices[ids[1]], self.vertices[ids[2]]]
        candidate_edges = [
            (ids[0], ids[1], pts[0], pts[1]),
            (ids[1], ids[2], pts[1], pts[2]),
            (ids[2], ids[0], pts[2], pts[0]),
        ]
        best = min(candidate_edges, key=lambda e: self._distance_sq_point_segment(hit_point, e[2], e[3]))
        return self._normalized_edge((best[0], best[1]))

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
