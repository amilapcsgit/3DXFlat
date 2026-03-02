from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile
import time
from typing import Dict, Iterable, List, Sequence, Tuple

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
from flatten_surface.import_export import _extract_open_patches_from_watertight, export_dxf, export_svg, get_unit_scale
from nesting import build_nesting_layout, export_nesting_layout
from qt_app.brep_import import is_brep_extension, is_occ_available, load_brep
from qt_app.flatten_panel import FlattenPanelWidget
from qt_app import mesh_cutting
from qt_app.mesh_io import load_mesh_file
from qt_app.unified_command_bar import UnifiedCommandBar
from qt_app.viewcube import ViewCubeWidget
from qt_app.viewport import ThreeDViewportWidget
from ui.icon_loader import load_icon_svg_file
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
        if is_brep_extension(path):
            self.status.emit("Loading CAD B-Rep...")
            brep = load_brep(path)
            self.progress.emit(40)
            vertices = np.asarray(brep.tri_mesh_vertices, dtype=np.float64)
            faces = np.asarray(brep.tri_mesh_faces, dtype=np.int64)
            tri_face_id = np.asarray(brep.tri_face_id, dtype=np.int64)
            if len(vertices) == 0 or len(faces) == 0:
                raise ValueError("B-Rep tessellation produced no valid triangles.")

            preview_faces = faces
            preview_indices = np.arange(len(faces), dtype=np.int64)
            if len(faces) > 120000:
                step = int(math.ceil(len(faces) / 120000.0))
                preview_faces = faces[::step]
                preview_indices = preview_indices[::step]

            self.progress.emit(70)
            mesh_checks = self._compute_mesh_checks_from_triangles(vertices, faces)
            self.progress.emit(100)
            return {
                "path": path,
                "model_type": "brep",
                "vertices": vertices,
                "faces": faces,
                "preview_faces": preview_faces,
                "preview_indices": preview_indices,
                "vertex_colors": None,
                "preview_face_colors": None,
                "mesh_checks": mesh_checks,
                "brep": {
                    "tri_face_id": tri_face_id,
                    "preview_tri_face_id": tri_face_id[preview_indices] if len(tri_face_id) == len(faces) else None,
                    "face_boundary_edge_ids": {int(k): [int(v) for v in vals] for k, vals in brep.face_boundary_edge_ids.items()},
                    "edge_polylines": {int(k): np.asarray(v, dtype=np.float64) for k, v in brep.edge_polylines.items()},
                    "face_count": int(len(brep.faces)),
                    "edge_count": int(len(brep.edges)),
                    "units": str(brep.units_label),
                    "bbox": tuple(float(x) for x in brep.bbox),
                },
            }

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

        mesh_checks = self._compute_mesh_checks_from_triangles(vertices, faces, area_faces=getattr(mesh, "area_faces", None))
        self.progress.emit(100)
        return {
            "path": path,
            "model_type": "mesh",
            "vertices": vertices,
            "faces": faces,
            "preview_faces": preview_faces,
            "preview_indices": preview_indices,
            "vertex_colors": vertex_colors,
            "preview_face_colors": preview_face_colors,
            "mesh_checks": mesh_checks,
            "brep": None,
        }

    @staticmethod
    def _compute_mesh_checks_from_triangles(
        vertices: np.ndarray,
        faces: np.ndarray,
        *,
        area_faces: np.ndarray | None = None,
    ) -> Dict[str, int]:
        faces = np.asarray(faces, dtype=np.int64)
        if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0:
            return {"open_edges": 0, "non_manifold_edges": 0, "degenerate_faces": 0}

        edges = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
        edges = np.sort(edges, axis=1)
        _, edge_use_counts = np.unique(edges, axis=0, return_counts=True)
        open_edges = int(np.sum(edge_use_counts == 1))
        non_manifold_edges = int(np.sum(edge_use_counts > 2))

        if area_faces is not None:
            area_arr = np.asarray(area_faces, dtype=np.float64)
            degenerate = int(np.sum(area_arr <= 1e-12))
        else:
            v = np.asarray(vertices, dtype=np.float64)
            tri = v[faces]
            area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
            degenerate = int(np.sum(area <= 1e-12))
        return {
            "open_edges": open_edges,
            "non_manifold_edges": non_manifold_edges,
            "degenerate_faces": degenerate,
        }

    def _run_flatten(self) -> Dict:
        self.status.emit("Running flatten solver...")
        self.progress.emit(5)
        self.progress.emit(20)
        vertices = np.asarray(self.payload["vertices"], dtype=np.float64)
        faces = np.asarray(self.payload["faces"], dtype=np.int64)
        selection_active = bool(self.payload.get("selection_active", False))
        anchor_edge_global = self.payload.get("anchor_edge")
        cut_edges_global = self.payload.get("cut_edges") or []
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
        anchor_edge = self._remap_edge_to_compact(anchor_edge_global, remap)
        cut_edges = self._remap_edges_to_compact(cut_edges_global, remap)
        warnings: List[str] = []
        topology_notes: Dict[str, Dict[str, int]] = {}

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

        if anchor_edge_global is not None and anchor_edge is None and selection_active:
            raise ValueError(
                "Anchor edge is outside the selected faces. "
                "Pick the anchor on the selected patch or clear the face selection."
            )

        topo_before = mesh_cutting.topology_report(compact_faces)
        topology_notes["before_cut"] = dict(topo_before)

        # Preserve historical behavior when the user has not selected faces/cuts:
        # try heuristic open-patch extraction from a closed solid.
        if (not selection_active) and topo_before.get("open_edges", 0) == 0 and len(cut_edges) == 0:
            auto_patch = self._auto_extract_open_patch(compact_vertices, compact_faces)
            if auto_patch is not None:
                compact_vertices, compact_faces = auto_patch
                topo_before = mesh_cutting.topology_report(compact_faces)
                topology_notes["before_cut"] = dict(topo_before)
                if anchor_edge is not None:
                    warnings.append("Anchor edge ignored because auto-patch extraction was used on the full solid.")
                    anchor_edge = None

        if topo_before.get("non_manifold_edges", 0) > 0:
            raise ValueError(
                f"Selected patch contains non-manifold edges ({topo_before['non_manifold_edges']}). "
                "Use a cleaner surface selection."
            )

        if topo_before.get("open_edges", 0) == 0 and len(cut_edges) == 0:
            raise ValueError(
                "Closed mesh/selection detected (no open boundary). "
                "Add relief cuts in Cut/Seam mode (and set an anchor edge), or select an open surface patch."
            )

        vertex_parent = np.arange(len(compact_vertices), dtype=np.int64)
        anchor_edge_for_uv = anchor_edge

        if len(cut_edges) > 0:
            cut_res = mesh_cutting.cut_mesh_along_edges(compact_vertices, compact_faces, cut_edges)
            used_cut_edges = [tuple(e) for e in cut_res.get("used_cut_edges", [])]
            missing_cut_edges = [tuple(e) for e in cut_res.get("missing_cut_edges", [])]
            if topo_before.get("open_edges", 0) == 0 and len(used_cut_edges) == 0:
                raise ValueError(
                    "The selected cut edges do not belong to the mesh patch being flattened. "
                    "Pick cut edges on the selected surface."
                )
            if missing_cut_edges:
                warnings.append(f"Ignored {len(missing_cut_edges)} cut edge(s) that were outside the flatten patch.")

            compact_vertices = np.asarray(cut_res["vertices"], dtype=np.float64)
            compact_faces = np.asarray(cut_res["faces"], dtype=np.int64)
            vertex_parent = np.asarray(cut_res["vertex_parent"], dtype=np.int64)
            topo_after_cut = dict(cut_res.get("topology_after", mesh_cutting.topology_report(compact_faces)))
            topology_notes["after_cut"] = dict(topo_after_cut)

            if topo_after_cut.get("non_manifold_edges", 0) > 0:
                raise ValueError(
                    f"Cut result is non-manifold ({topo_after_cut['non_manifold_edges']} edge(s)). "
                    "Adjust the cut chain."
                )
            if topo_after_cut.get("open_edges", 0) == 0:
                raise ValueError(
                    "Cut edges did not create an open boundary. "
                    "Add a continuous cut chain that opens the selected closed surface."
                )
            if topo_after_cut.get("connected_components", 0) != 1 or topo_after_cut.get("boundary_loops", 0) <= 0:
                warnings.append(
                    "Cut result is not a single disk-like patch (multiple components or no boundary loop). "
                    "Flatten may be unstable; adjust cuts."
                )

            if anchor_edge is not None:
                anchor_edge_for_uv = mesh_cutting.choose_anchor_edge_instance(compact_faces, vertex_parent, anchor_edge)
                if anchor_edge_for_uv is None:
                    warnings.append("Anchor edge could not be mapped after cutting; solver orientation was left automatic.")
        else:
            topology_notes["after_cut"] = dict(topo_before)
            if anchor_edge is not None:
                anchor_edge_for_uv = mesh_cutting.choose_anchor_edge_instance(
                    compact_faces,
                    np.arange(len(compact_vertices), dtype=np.int64),
                    anchor_edge,
                )
                if anchor_edge_for_uv is None:
                    warnings.append("Anchor edge is not part of the flatten patch; solver orientation was left automatic.")

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

        if anchor_edge_for_uv is not None:
            ok = self._apply_anchor_orientation_and_reexport(
                flatten_result=res,
                anchor_edge=anchor_edge_for_uv,
                path_output=str(self.payload["path_output"]),
                input_unit=str(self.payload["input_unit"]),
                seam_allowance_mm=float(self.payload["seam_allowance_mm"]),
                label_text=self.payload.get("label_text"),
            )
            if not ok:
                warnings.append("Anchor edge was degenerate in UV; output orientation was left unchanged.")

        self.progress.emit(95)
        self.progress.emit(100)
        return {
            "path_output": self.payload["path_output"],
            "flatten_result": res,
            "warnings": warnings,
            "topology": topology_notes,
        }

    @staticmethod
    def _remap_edge_to_compact(edge: Sequence[int] | None, remap: Dict[int, int]) -> Tuple[int, int] | None:
        if edge is None:
            return None
        if len(edge) != 2:
            return None
        a = remap.get(int(edge[0]))
        b = remap.get(int(edge[1]))
        if a is None or b is None or int(a) == int(b):
            return None
        aa = int(a)
        bb = int(b)
        return (aa, bb) if aa < bb else (bb, aa)

    @classmethod
    def _remap_edges_to_compact(cls, edges: Iterable[Sequence[int]], remap: Dict[int, int]) -> List[Tuple[int, int]]:
        mapped: List[Tuple[int, int]] = []
        seen: set[Tuple[int, int]] = set()
        for edge in edges or []:
            m = cls._remap_edge_to_compact(edge, remap)
            if m is None or m in seen:
                continue
            seen.add(m)
            mapped.append(m)
        mapped.sort()
        return mapped

    @staticmethod
    def _auto_extract_open_patch(vertices: np.ndarray, faces: np.ndarray) -> Tuple[np.ndarray, np.ndarray] | None:
        try:
            mesh = trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(faces), process=False)
            if not bool(getattr(mesh, "is_watertight", False)):
                return None
            patches = _extract_open_patches_from_watertight(mesh)
            if not patches:
                return None
            patch = patches[0]
            return np.asarray(patch.vertices, dtype=np.float64), np.asarray(patch.faces, dtype=np.int64)
        except Exception:
            return None

    @staticmethod
    def _apply_anchor_orientation_and_reexport(
        *,
        flatten_result: Dict,
        anchor_edge: Sequence[int],
        path_output: str,
        input_unit: str,
        seam_allowance_mm: float,
        label_text: str | None,
    ) -> bool:
        unwrap = np.asarray(flatten_result.get("unwrap"), dtype=np.float64)
        if unwrap.ndim != 2 or unwrap.shape[1] != 2:
            return False
        if len(anchor_edge) != 2:
            return False
        a = int(anchor_edge[0])
        b = int(anchor_edge[1])
        if a < 0 or b < 0 or a >= len(unwrap) or b >= len(unwrap) or a == b:
            return False

        p0 = np.asarray(unwrap[a], dtype=np.float64)
        p1 = np.asarray(unwrap[b], dtype=np.float64)
        d = p1 - p0
        dn = float(np.linalg.norm(d))
        if not np.isfinite(dn) or dn <= 1e-12:
            return False

        angle = -math.atan2(float(d[1]), float(d[0]))
        c = math.cos(angle)
        s = math.sin(angle)
        rot = np.array([[c, -s], [s, c]], dtype=np.float64)

        unwrap_aligned = (unwrap - p0[None, :]) @ rot.T
        flatten_result["unwrap"] = unwrap_aligned

        relief_path = flatten_result.get("relief_path_2d")
        if relief_path is not None:
            relief_arr = np.asarray(relief_path, dtype=np.float64)
            if relief_arr.ndim == 2 and relief_arr.shape[1] == 2 and len(relief_arr) >= 2:
                flatten_result["relief_path_2d"] = (relief_arr - p0[None, :]) @ rot.T

        bounds = flatten_result.get("export_bounds") or []
        scale = get_unit_scale(input_unit)
        if str(path_output).lower().endswith(".dxf"):
            export_dxf(
                flatten_result["unwrap"],
                bounds,
                path_output,
                scale=scale,
                seam_allowance_mm=seam_allowance_mm,
                align_to_x=False,
                label_text=label_text,
                relief_cut_path=flatten_result.get("relief_path_2d"),
            )
        else:
            export_svg(flatten_result["unwrap"], bounds, path_output, scale=scale)
        return True

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
                "Select an open surface patch or add relief cuts in Cut/Seam mode."
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
        self._debug_selection = str(os.getenv("DXF_DEBUG_SELECTION", "0")).strip() == "1"
        self.setWindowTitle("3DXFlat Advanced (Qt)")
        self.setMinimumSize(1100, 700)
        self._settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self._seam_debounce = QTimer(self)
        self._seam_debounce.setSingleShot(True)
        self._seam_debounce.setInterval(120)
        self._seam_debounce.timeout.connect(self._apply_seam_to_preview)

        self.loaded_model_path: str | None = None
        self.loaded_model_type: str = "mesh"
        self.loaded_vertices: np.ndarray | None = None
        self.loaded_faces: np.ndarray | None = None
        self.loaded_preview_faces: np.ndarray | None = None
        self.loaded_brep: Dict | None = None
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
        self.viewport_splitter.setSizes([4, 2])

        self.flatten_panel = FlattenPanelWidget(central)
        self.flatten_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(4)
        self.workspace_splitter.setContentsMargins(0, 0, 0, 0)
        self.workspace_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.workspace_splitter.setStyleSheet(
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
        self.workspace_splitter.addWidget(self.flatten_panel)
        self.workspace_splitter.addWidget(self.viewport_splitter)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 10)
        self.workspace_splitter.setSizes([320, 1280])

        self.view_cube = ViewCubeWidget(self.viewport)
        self.view_cube.faceClicked.connect(self._on_viewcube_face_clicked)
        self.view_cube.setWindowFlags(self.view_cube.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.view_cube.show()
        self.viewport.cameraChanged.connect(self._on_viewport_camera_changed)
        self.viewport.facesSelected.connect(self._on_faces_selected)
        self.viewport.seamStateChanged.connect(self._on_seam_state_changed)
        self.viewport.modelDropped.connect(self.load_model_file)
        self.viewport.flattenRequested.connect(self.run_flatten)
        self.viewport.splitToggleRequested.connect(self.toggle_2d_preview)
        self.viewport.installEventFilter(self)
        self._position_viewcube()
        self._set_2d_preview_visible(False)

        # PH2-VP: zoned header area (Row1 system bar + Row2 command bar) is the
        # only visible header/command surface above the viewport.
        self.header_area = QFrame(central)
        self.header_area.setObjectName("headerArea")
        self.header_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header_area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.header_area.setAutoFillBackground(True)
        self.header_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header_layout = QVBoxLayout(self.header_area)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        self.row1_system_bar = QFrame(self.header_area)
        self.row1_system_bar.setObjectName("row1SystemBar")
        self.row1_system_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.row1_system_bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.row1_system_bar.setAutoFillBackground(True)
        self.row1_system_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.row1_system_bar.setFixedHeight(32)
        row1_layout = QHBoxLayout(self.row1_system_bar)
        row1_layout.setContentsMargins(12, 4, 12, 4)
        row1_layout.setSpacing(8)

        def _make_system_bar_button(text: str, icon_name: str) -> QToolButton:
            btn = QToolButton(self.row1_system_bar)
            btn.setObjectName("SystemBarButton")
            btn.setText(text)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(24)
            btn.setMinimumWidth(76)
            icon = load_icon_svg_file(f"ui/icons/Industrial_SVG_Set_v1/{icon_name}.svg", size=16, color=tokens.TEXT_SECONDARY)
            if not icon.isNull():
                btn.setIcon(icon)
                btn.setIconSize(QSize(16, 16))
            return btn

        self.system_settings_btn = _make_system_bar_button("Settings", "settings")
        self.system_about_btn = _make_system_bar_button("About", "about")
        row1_layout.addStretch(1)
        row1_layout.addWidget(self.system_settings_btn)
        row1_layout.addWidget(self.system_about_btn)

        self.unified_command_bar = UnifiedCommandBar(self.header_area)
        self.unified_command_bar.setObjectName("row2CommandBar")

        header_layout.addWidget(self.row1_system_bar, 0)
        header_layout.addWidget(self.unified_command_bar, 0)
        self.header_area.setFixedHeight(self.row1_system_bar.height() + self.unified_command_bar.height())
        self.ribbon = None

        # Compatibility aliases (callbacks are wired in PH2-S3).
        bar = self.unified_command_bar
        self.import_btn_setup = bar.btn_import_model
        self.reset_camera_btn = bar.btn_reset_view
        self.wireframe_btn = bar.btn_wireframe
        self.grid_btn = bar.btn_grid

        self.smart_select_btn = bar.btn_smart_select
        self.single_pick_btn = bar.btn_single_pick
        self.clear_selection_btn = bar.btn_clear
        self.invert_selection_btn = bar.btn_invert
        self.isolate_btn = bar.btn_isolate
        self.toggle_2d_btn = bar.btn_toggle_2d

        # Keep only the mode toggle in the command row. Seam actions live in the left panel.
        row2 = bar.row2_layout
        self.cut_seam_mode_btn = QPushButton("Cut/Seam", self.header_area)
        self.cut_seam_mode_btn.setObjectName("ToggleButton")
        self.cut_seam_mode_btn.setCheckable(True)
        self.cut_seam_mode_btn.setMinimumHeight(40)
        self.cut_seam_mode_btn.setMaximumHeight(40)
        self.cut_seam_mode_btn.setMinimumWidth(112)
        self.cut_seam_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        row2.insertWidget(row2.indexOf(self.single_pick_btn) + 1, self.cut_seam_mode_btn)

        self.method_combo = bar.method_combo
        self.technical_mode_btn = bar.btn_technical
        self.show_edges_btn = bar.btn_edges
        self.selected_label = bar.selected_label
        self.run_flatten_btn_tab = bar.btn_run_flatten
        self.run_flatten_btn_tab.setObjectName("btnRunFlattenPrimary")
        self.quality_gauge = bar.quality_gauge

        self.seam_slider = bar.seam_slider
        self.seam_label = bar.seam_label
        self.nest_btn = bar.btn_nest
        self.export_btn_top = bar.btn_export_dxf
        self.export_btn_top.setObjectName("btnExportDxfSecondary")
        self.settings_btn_top = self.system_settings_btn
        self.about_btn_top = self.system_about_btn
        self.export_path_label = bar.export_path_label

        self.units_combo = bar.units_combo
        self.scale_label = bar.scale_label
        self.mesh_info_label = bar.mesh_info_label

        self.selection_mode_group = QButtonGroup(self)
        self.selection_mode_group.setExclusive(True)
        self.selection_mode_group.addButton(self.smart_select_btn)
        self.selection_mode_group.addButton(self.single_pick_btn)
        self.selection_mode_group.addButton(self.cut_seam_mode_btn)

        self._wire_unified_command_bar_actions()

        root.addWidget(self.header_area, 0)
        root.addWidget(self.workspace_splitter, 1)
        root.setStretch(0, 0)
        root.setStretch(1, 10)

        self.setCentralWidget(central)
        self._apply_selection_mode()
        self._on_seam_state_changed({"active_edge": None, "anchor_edge": None, "cut_edges": []})
        self.flatten_panel.set_pick_mode("edge")
        self.flatten_panel.set_advanced_mesh_seam_enabled(False)
        self.flatten_panel.set_precision_value(int(self.seam_slider.value()))
        self._update_workflow_enablement()

    def _wire_unified_command_bar_actions(self) -> None:
        # PH2-S3: UI-only signal wiring to existing handlers.
        self.import_btn_setup.setShortcut("Ctrl+O")
        self.import_btn_setup.clicked.connect(self.import_3d_dialog)

        self.reset_camera_btn.clicked.connect(self.viewport.reset_camera)
        self.wireframe_btn.toggled.connect(self.viewport.set_wireframe_mode)
        self.grid_btn.toggled.connect(self.viewport.set_grid_visible)

        self.smart_select_btn.clicked.connect(self._apply_selection_mode)
        self.single_pick_btn.clicked.connect(self._apply_selection_mode)
        self.cut_seam_mode_btn.clicked.connect(self._apply_selection_mode)
        self.clear_selection_btn.clicked.connect(self.viewport.clear_selection)
        self.invert_selection_btn.clicked.connect(self.viewport.invert_selection)
        self.isolate_btn.toggled.connect(self._on_isolate_toggled)
        self.toggle_2d_btn.toggled.connect(self.toggle_2d_preview)
        self.flatten_panel.requestSetAnchor.connect(self._on_set_anchor_clicked)
        self.flatten_panel.requestToggleCut.connect(self._on_toggle_cut_clicked)
        self.flatten_panel.requestRemoveCut.connect(self._on_remove_cut_from_panel)
        self.flatten_panel.requestClearCuts.connect(self._on_clear_cuts_clicked)
        self.flatten_panel.requestAutoGuessAnchor.connect(self._on_auto_guess_anchor_clicked)
        self.flatten_panel.precisionChanged.connect(self._on_panel_precision_changed)
        self.flatten_panel.pickModeChanged.connect(self._on_panel_pick_mode_changed)
        self.flatten_panel.advancedMeshSeamChanged.connect(self._on_advanced_mesh_seam_changed)

        self.units_combo.currentTextChanged.connect(self._update_dimension_label_only)
        self.technical_mode_btn.toggled.connect(self.viewport.set_technical_mode)
        self.show_edges_btn.toggled.connect(self.viewport.set_edges_visible)

        self.run_flatten_btn_tab.setShortcut("F5")
        self.run_flatten_btn_tab.clicked.connect(self.run_flatten)

        self.seam_slider.valueChanged.connect(self._on_seam_slider_changed)
        self.nest_btn.clicked.connect(self.run_nesting_job)

        self.export_btn_top.setShortcut("Ctrl+E")
        self.export_btn_top.clicked.connect(self.export_dxf)
        self.settings_btn_top.clicked.connect(self._show_settings_dialog)
        self.about_btn_top.clicked.connect(self._show_about_dialog)

        # Reassert current toggle state in the viewport after connecting signals.
        try:
            self.viewport.set_grid_visible(bool(self.grid_btn.isChecked()))
            self.viewport.set_wireframe_mode(bool(self.wireframe_btn.isChecked()))
            self.viewport.set_technical_mode(bool(self.technical_mode_btn.isChecked()))
            self.viewport.set_edges_visible(bool(self.show_edges_btn.isChecked()))
        except Exception:
            pass

    def _build_top_toolbar(self) -> None:
        # PH2 unified command bar mode disables the legacy top-toolbar path.
        return

    def _build_ribbon(self) -> QTabWidget:
        # PH2 unified command bar mode disables the legacy tabbed ribbon path.
        tabs = QTabWidget(self)
        tabs.hide()
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
        if self._debug_selection:
            print(
                "[DXF_DEBUG_SELECTION] _on_viewcube_face_clicked() "
                f"face={face} faces_selected={len(self.viewport.get_selected_faces())} "
                f"anchor={self.viewport.get_anchor_edge()} cuts={len(self.viewport.get_cut_edges())}"
            )
        self.viewport.apply_view_preset(face)
        self.view_cube.raise_()
        self.statusBar().showMessage(f"View: {face.title()}", 1500)

    def _on_faces_selected(self, faces: List[int]) -> None:
        self.selected_label.setText(f"Selected: {len(faces)}")
        self.flatten_panel.set_faces_count(len(faces))
        if self.loaded_model_type == "brep":
            self.log(f"INFO | CAD face selection updated: {len(faces)} face(s)")
        else:
            self.log(f"INFO | Surface selection updated: {len(faces)} face(s)")
        if hasattr(self, "isolate_btn") and not faces and self.isolate_btn.isChecked():
            self.isolate_btn.blockSignals(True)
            self.isolate_btn.setChecked(False)
            self.isolate_btn.blockSignals(False)

    def _apply_selection_mode(self) -> None:
        if self.smart_select_btn.isChecked():
            self.viewport.set_selection_mode("smart")
            self.statusBar().showMessage("Face selection: Smart", 1500)
            self.flatten_panel.set_guidance_text(
                "Seleziona facce con Smart/Single.\n"
                "Poi passa a Cut/Seam per scegliere bordo e tagli."
            )
        elif self.single_pick_btn.isChecked():
            self.viewport.set_selection_mode("single")
            self.statusBar().showMessage("Face selection: Single Pick", 1500)
            self.flatten_panel.set_guidance_text(
                "Seleziona facce con click (Ctrl aggiunge, Alt rimuove).\n"
                "Poi attiva Cut/Seam."
            )
        elif hasattr(self, "cut_seam_mode_btn") and self.cut_seam_mode_btn.isChecked():
            self.viewport.set_selection_mode("cut")
            self.statusBar().showMessage("Cut/Seam mode: hover edge, click=cut, Shift+click=anchor.", 2500)
            self.flatten_panel.set_guidance_text(
                "Cut/Seam: passa vicino al bordo per evidenziare.\n"
                "Click = taglio di scarico.\n"
                "Shift+Click = bordo anchor.\n"
                "Modalita bordo: Edge/Chain dal pannello."
            )
        else:
            self.viewport.set_selection_mode("off")

    def _on_seam_state_changed(self, payload: Dict | object) -> None:
        info = payload if isinstance(payload, dict) else {}
        model_type = str(info.get("model_type", self.loaded_model_type)).strip().lower()
        pick_mode = str(info.get("brep_pick_mode", "edge")).strip().lower()
        if model_type == "brep":
            self.flatten_panel.set_pick_mode("chain" if pick_mode == "chain" else "edge")
        active = info.get("hover_edge") or info.get("active_edge")
        anchor = info.get("anchor_edge")
        cuts = info.get("cut_edges") or []
        cut_count = int(info.get("cut_chain_count", len(cuts)))
        boundary_edges = {self._norm_edge(e) for e in (info.get("boundary_edges") or [])}
        anchor_boundary = None
        if anchor is not None:
            anchor_boundary = self._norm_edge(anchor) in boundary_edges
        self.flatten_panel.set_anchor_edge(
            anchor,
            label=None if anchor is None else self._edge_label_basic(anchor, boundary=anchor_boundary),
        )
        self.flatten_panel.set_cut_edges(
            cuts,
            labels={
                self._norm_edge(edge): self._edge_label_basic(edge, boundary=(self._norm_edge(edge) in boundary_edges))
                for edge in cuts
            },
        )

        active_txt = "-" if not active else f"v{int(active[0])}-v{int(active[1])}"
        patch_status = self._patch_state_text()
        anchor_status = "none" if not anchor else "set"
        strategy = str(info.get("pick_strategy", "-"))
        self.flatten_panel.set_status_line(
            f"Seam: A[{anchor_status}]  C[{cut_count}]  Patch: {patch_status}  Hover: {active_txt}  Pick:{strategy}"
        )

    def _on_set_anchor_clicked(self) -> None:
        edge = self.viewport.set_anchor_from_active_edge()
        if edge is None:
            QMessageBox.information(
                self,
                "Set Anchor",
                "No active edge selected.\n\nEnable Cut/Seam mode and click near a mesh edge first.",
            )
            return
        if edge[0] < 0 or edge[1] < 0:
            self.log("INFO | Anchor chain set.")
            self.statusBar().showMessage("Anchor chain set.", 2500)
            return
        self.log(f"INFO | Anchor edge set: {edge[0]}-{edge[1]}")
        self.statusBar().showMessage(f"Anchor edge set: {edge[0]}-{edge[1]}", 2500)

    def _on_toggle_cut_clicked(self) -> None:
        result = self.viewport.toggle_cut_from_active_edge()
        if result is None:
            QMessageBox.information(
                self,
                "Cut Edge",
                "No active edge selected.\n\nEnable Cut/Seam mode and click near a mesh edge first.",
            )
            return
        action, edge = result
        if action == "anchor_conflict":
            QMessageBox.warning(
                self,
                "Cut Edge",
                "The active edge is the current anchor edge.\n\nChoose another edge or change the anchor first.",
            )
            return
        if edge[0] < 0 or edge[1] < 0:
            verb = "added" if action == "added" else "removed"
            self.log(f"INFO | Cut chain {verb}.")
            self.statusBar().showMessage(f"Cut chain {verb}.", 2500)
            return
        verb = "added" if action == "added" else "removed"
        self.log(f"INFO | Cut edge {verb}: {edge[0]}-{edge[1]}")
        self.statusBar().showMessage(f"Cut edge {verb}: {edge[0]}-{edge[1]}", 2500)

    def _on_clear_cuts_clicked(self) -> None:
        self.viewport.clear_cut_edges()
        self.log("INFO | Cleared anchor and cut edges.")
        self.statusBar().showMessage("Cleared anchor and cut edges.", 2000)

    def _on_remove_cut_from_panel(self, edge_obj: object) -> None:
        if not edge_obj:
            return
        try:
            edge = (int(edge_obj[0]), int(edge_obj[1]))
        except Exception:
            return
        removed = self.viewport.remove_cut_edge(edge)
        if removed:
            self.log(f"INFO | Cut edge removed: {removed[0]}-{removed[1]}")
            self.statusBar().showMessage(f"Cut edge removed: {removed[0]}-{removed[1]}", 2000)

    def _on_auto_guess_anchor_clicked(self) -> None:
        edge = self.viewport.auto_guess_anchor_edge()
        if edge is None:
            QMessageBox.information(
                self,
                "Auto Bordo",
                "Impossibile stimare automaticamente il bordo.\n\nSeleziona facce valide e riprova.",
            )
            return
        if edge[0] < 0 or edge[1] < 0:
            self.log("INFO | Auto anchor chain selected.")
            self.statusBar().showMessage("Auto bordo chain selezionato.", 2200)
            return
        self.log(f"INFO | Auto anchor selected: {edge[0]}-{edge[1]}")
        self.statusBar().showMessage(f"Auto bordo: {edge[0]}-{edge[1]}", 2200)

    def _on_panel_precision_changed(self, value: int) -> None:
        ivalue = int(value)
        if int(self.seam_slider.value()) == ivalue:
            return
        self.seam_slider.blockSignals(True)
        self.seam_slider.setValue(ivalue)
        self.seam_slider.blockSignals(False)
        self._on_seam_slider_changed(ivalue)

    def _on_panel_pick_mode_changed(self, mode: str) -> None:
        normalized = str(mode).strip().lower()
        self.viewport.set_brep_pick_mode(normalized)
        if normalized == "chain":
            self.statusBar().showMessage("B-Rep seam selection: Chain mode.", 1800)
        else:
            self.statusBar().showMessage("B-Rep seam selection: Edge mode.", 1800)

    def _on_advanced_mesh_seam_changed(self, enabled: bool) -> None:
        self.viewport.set_advanced_mesh_seam_enabled(bool(enabled))
        if enabled:
            self.statusBar().showMessage("Advanced mesh seam enabled: use Ctrl+Click in Cut/Seam mode.", 2600)
        else:
            self.statusBar().showMessage("Advanced mesh seam disabled.", 1600)

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
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import 3D Model",
            "",
            "3D files (*.stl *.obj *.stp *.step *.iges *.igs)",
        )
        if path:
            self.load_model_file(path)

    def load_model_file(self, path: str) -> None:
        if is_brep_extension(path):
            ok, reason = is_occ_available()
            if not ok:
                detail = f"\n\nImport error: {reason}" if reason else ""
                QMessageBox.information(
                    self,
                    "B-Rep Import Optional Component",
                    "STEP/IGES import requires optional dependency `pythonocc-core`.\n\n"
                    "Install with:\n"
                    "pip install pythonocc-core"
                    f"{detail}",
                )
                self.log("WARN | STEP/IGES import requested but pythonocc-core is not available.")
                return
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
        model_type = str(payload.get("model_type", "mesh")).strip().lower()
        if model_type not in {"mesh", "brep"}:
            model_type = "mesh"
        brep_meta = payload.get("brep") if model_type == "brep" else None
        self.loaded_model_path = path
        self.loaded_model_type = model_type
        self.loaded_vertices = vertices
        self.loaded_faces = faces
        self.loaded_preview_faces = preview_faces
        self.loaded_brep = brep_meta if isinstance(brep_meta, dict) else None
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
            brep_metadata=self.loaded_brep,
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
        self.flatten_panel.set_faces_count(0)
        self.flatten_panel.set_anchor_edge(None)
        self.flatten_panel.set_cut_edges([])
        self.flatten_panel.set_status_line("Seam: A[none]  C[0]  Patch: -")
        self._update_workflow_enablement()
        self._update_status_metadata()
        if self.loaded_model_type == "brep" and self.loaded_brep:
            face_count = int(self.loaded_brep.get("face_count", 0))
            edge_count = int(self.loaded_brep.get("edge_count", 0))
            self.log(
                f"INFO | CAD model loaded: {Path(path).name} "
                f"(BRep faces={face_count}, BRep edges={edge_count}, tris={len(faces)})"
            )
        else:
            self.log(f"INFO | Model loaded: {Path(path).name} ({len(vertices)} verts, {len(faces)} faces)")

    def _flatten_faces_payload(self) -> np.ndarray | None:
        source_faces = self.viewport.pick_faces if self.viewport.pick_faces is not None else self.loaded_faces
        if source_faces is None:
            return None
        selected = self.viewport.get_selected_faces()
        if self.loaded_model_type == "brep" and self.loaded_brep is not None:
            tri_face_id = np.asarray(self.loaded_brep.get("tri_face_id", np.empty((0,), dtype=np.int64)), dtype=np.int64)
            if len(tri_face_id) == len(source_faces) and selected:
                sel = np.asarray(sorted({int(x) for x in selected}), dtype=np.int64)
                tri_idx = np.nonzero(np.isin(tri_face_id, sel))[0]
                if len(tri_idx) == 0:
                    return np.empty((0, 3), dtype=np.int64)
                return np.asarray(source_faces[tri_idx], dtype=np.int64)
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
        selection_active = bool(self.viewport.get_selected_faces())
        tmp = Path(tempfile.gettempdir()) / "3dxflat_qt_preview.dxf"
        method = self.method_combo.currentText() or "ARAP"
        self._run_worker_task(
            task_name="flatten",
            payload={
                "vertices": self.loaded_vertices,
                "faces": faces_to_flatten,
                "selection_active": selection_active,
                "anchor_edge": self.viewport.get_anchor_edge(),
                "cut_edges": self.viewport.get_cut_edges(),
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
        self._show_flatten_warnings(payload)

    def _run_flatten_to_path(self, path: str) -> None:
        faces_to_flatten = self._flatten_faces_payload()
        if self.loaded_vertices is None or faces_to_flatten is None or len(faces_to_flatten) == 0:
            QMessageBox.warning(self, "Export", "No valid faces selected.")
            return
        selection_active = bool(self.viewport.get_selected_faces())
        method = self.method_combo.currentText() or "ARAP"
        self._run_worker_task(
            task_name="flatten",
            payload={
                "vertices": self.loaded_vertices,
                "faces": faces_to_flatten,
                "selection_active": selection_active,
                "anchor_edge": self.viewport.get_anchor_edge(),
                "cut_edges": self.viewport.get_cut_edges(),
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
        self._show_flatten_warnings(payload)

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
        self.flatten_panel.set_precision_value(int(value))
        self.viewport.mark_seam_candidates_dirty("precision_changed")
        self._seam_debounce.start()

    def _apply_seam_to_preview(self) -> None:
        self.preview2d.set_seam(float(self.seam_slider.value()))

    def _show_flatten_warnings(self, payload: Dict) -> None:
        warnings = payload.get("warnings") or []
        if not warnings:
            return
        text = "\n\n".join(str(w) for w in warnings)
        QMessageBox.warning(self, "Flatten Warning", text)
        for w in warnings:
            self.log(f"WARN | {w}")

    @staticmethod
    def _norm_edge(edge: Sequence[int]) -> Tuple[int, int]:
        a = int(edge[0])
        b = int(edge[1])
        return (a, b) if a < b else (b, a)

    def _edge_length_mm(self, edge: Sequence[int]) -> float | None:
        if self.loaded_vertices is None:
            return None
        a, b = self._norm_edge(edge)
        if a < 0 or b < 0 or a >= len(self.loaded_vertices) or b >= len(self.loaded_vertices):
            return None
        scale = get_unit_scale(self.units_combo.currentText())
        return float(np.linalg.norm(self.loaded_vertices[a] - self.loaded_vertices[b]) * scale)

    def _edge_label_basic(self, edge: Sequence[int], *, boundary: bool | None = None) -> str:
        a, b = self._norm_edge(edge)
        length = self._edge_length_mm((a, b))
        btxt = ""
        if boundary is not None:
            btxt = " boundary=Y" if bool(boundary) else " boundary=N"
        if length is None:
            return f"Edge: v{a}-v{b}{btxt}"
        return f"Edge: v{a}-v{b} (len={length:.1f} mm{btxt})"

    def _patch_state_text(self) -> str:
        source_faces = self.viewport.pick_faces if self.viewport.pick_faces is not None else self.loaded_faces
        if source_faces is None or len(source_faces) == 0:
            return "-"
        selected = self.viewport.get_selected_faces()
        if selected and self.loaded_model_type == "brep" and self.loaded_brep is not None:
            tri_face_id = np.asarray(self.loaded_brep.get("tri_face_id", np.empty((0,), dtype=np.int64)), dtype=np.int64)
            if len(tri_face_id) == len(source_faces):
                sel = np.asarray(sorted({int(x) for x in selected}), dtype=np.int64)
                tri_idx = np.nonzero(np.isin(tri_face_id, sel))[0]
                if len(tri_idx) == 0:
                    return "-"
                faces = np.asarray(source_faces[tri_idx], dtype=np.int64)
            else:
                faces = np.asarray(source_faces, dtype=np.int64)
        elif selected:
            idx = np.asarray(selected, dtype=np.int64)
            idx = idx[(idx >= 0) & (idx < len(source_faces))]
            if len(idx) == 0:
                return "-"
            faces = np.asarray(source_faces[idx], dtype=np.int64)
        else:
            faces = np.asarray(source_faces, dtype=np.int64)
        topo = mesh_cutting.topology_report(faces)
        state = "open" if topo.get("open_edges", 0) > 0 else "closed"
        return (
            f"{state} "
            f"(loops={topo.get('boundary_loops', 0)}, "
            f"comp={topo.get('connected_components', 0)})"
        )

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
            self.cut_seam_mode_btn,
            can_flatten,
            "Cut/Seam mode (edge picking for anchor and relief cuts)",
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
            self.flatten_panel.btn_set_anchor,
            can_flatten,
            "Set anchor edge from hovered edge (or Shift+Click in viewport)",
            flatten_reason,
        )
        self._set_control_state(
            self.flatten_panel.btn_auto_anchor,
            can_flatten,
            "Auto-pick a deterministic boundary anchor",
            flatten_reason,
        )
        self._set_control_state(
            self.flatten_panel.btn_toggle_cut,
            can_flatten,
            "Add/remove cut from hovered edge (or click in viewport)",
            flatten_reason,
        )
        self._set_control_state(
            self.flatten_panel.btn_remove_selected,
            can_flatten,
            "Remove selected cut from list",
            flatten_reason,
        )
        self._set_control_state(
            self.flatten_panel.btn_clear_cuts,
            can_flatten,
            "Clear anchor and cut edges",
            flatten_reason,
        )
        self.flatten_panel.cut_edges_list.setEnabled(can_flatten)
        self.flatten_panel.precision_slider.setEnabled(can_flatten)
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
