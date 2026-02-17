from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import ezdxf
import numpy as np
import trimesh
from PySide6.QtCore import QSettings, Qt, QTimer, QPointF, QRectF, QSize
from PySide6.QtGui import QAction, QColor, QContextMenuEvent, QPainter, QPainterPath, QPen, QBrush, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon

from flatten_surface.flatten_surface import flatten_mesh
from flatten_surface.import_export import get_unit_scale
from nesting import build_nesting_layout, export_nesting_layout, Placement
from qt_app.mesh_io import load_mesh_file


class BreadcrumbBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: Dict[int, QToolButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        steps = ["1. Import", "2. Select & Flatten", "3. Nest & Optimize", "4. Export"]
        for idx, text in enumerate(steps):
            btn = QToolButton(self)
            btn.setText(text)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            self._buttons[idx] = btn
            layout.addWidget(btn)
            if idx < len(steps) - 1:
                sep = QLabel(">", self)
                sep.setStyleSheet("color:#8a94a6;")
                layout.addWidget(sep)
        layout.addStretch(1)
        self.set_step(0)

    def set_step(self, step: int) -> None:
        if step not in self._buttons:
            return
        self._buttons[step].setChecked(True)
        for idx, btn in self._buttons.items():
            btn.setStyleSheet(
                "QToolButton { color: #f0f3f8; font-weight: 600; }"
                if idx <= step
                else "QToolButton { color: #8a94a6; }"
            )

    def bind_step_handlers(self, on_click) -> None:
        for idx, btn in self._buttons.items():
            btn.clicked.connect(lambda _checked=False, i=idx: on_click(i))


class CadGraphicsView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QColor("#22252b"))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._panning = False
        self._pan_start = None
        self._on_key_nudge = None

    def wheelEvent(self, event) -> None:  # noqa: N802
        self.scale(1.15 if event.angleDelta().y() > 0 else (1.0 / 1.15), 1.15 if event.angleDelta().y() > 0 else (1.0 / 1.15))

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

    def set_key_nudge_callback(self, callback) -> None:
        self._on_key_nudge = callback

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._on_key_nudge is not None:
            mult = 10 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1
            key = event.key()
            if key == Qt.Key.Key_Left:
                self._on_key_nudge(-mult, 0)
                event.accept()
                return
            if key == Qt.Key.Key_Right:
                self._on_key_nudge(mult, 0)
                event.accept()
                return
            if key == Qt.Key.Key_Up:
                self._on_key_nudge(0, -mult)
                event.accept()
                return
            if key == Qt.Key.Key_Down:
                self._on_key_nudge(0, mult)
                event.accept()
                return
        super().keyPressEvent(event)


class Flatten2DPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fold_polygon: Polygon | None = None
        self._seam_mm = 12.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        title = QLabel("2D Pattern Preview (CAD)", self)
        title.setStyleSheet("font-size:14px; font-weight:600; color:#cfd7e3;")
        layout.addWidget(title)

        self.scene = QGraphicsScene(self)
        self.view = CadGraphicsView(self.scene, self)
        layout.addWidget(self.view, 1)

        self.fold_item = QGraphicsPathItem()
        self.fold_item.setPen(QPen(QColor("#7fc3ff"), 1.2))
        self.scene.addItem(self.fold_item)

        self.cut_item = QGraphicsPathItem()
        self.cut_item.setPen(QPen(QColor("#ff5f5f"), 1.2))
        self.scene.addItem(self.cut_item)

        self.info = QLabel("No flattened shape yet.", self)
        self.info.setStyleSheet("color:#93a0b5;")
        layout.addWidget(self.info)

    def set_fold_polygon(self, poly: Polygon | None, fit: bool = True) -> None:
        self._fold_polygon = poly
        self.render_preview(fit=fit)

    def set_seam(self, seam_mm: float) -> None:
        self._seam_mm = max(0.0, float(seam_mm))
        self.render_preview(fit=False)

    def _polygon_to_path(self, poly: Polygon) -> QPainterPath:
        path = QPainterPath()
        self._add_ring(path, poly.exterior.coords)
        for hole in poly.interiors:
            self._add_ring(path, hole.coords)
        return path

    def _add_ring(self, path: QPainterPath, coords: Iterable[Tuple[float, float]]) -> None:
        pts = list(coords)
        if len(pts) < 2:
            return
        x0, y0 = pts[0]
        path.moveTo(x0, -y0)
        for x, y in pts[1:]:
            path.lineTo(x, -y)
        path.closeSubpath()

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


def polygon_to_qpath(poly: Polygon, invert_y: bool = False) -> QPainterPath:
    path = QPainterPath()
    if poly.is_empty:
        return path

    def add_ring(coords):
        pts = list(coords)
        if len(pts) < 2:
            return
        x0, y0 = pts[0]
        y0 = -y0 if invert_y else y0
        path.moveTo(x0, y0)
        for x, y in pts[1:]:
            yv = -y if invert_y else y
            path.lineTo(x, yv)
        path.closeSubpath()

    add_ring(poly.exterior.coords)
    for hole in poly.interiors:
        add_ring(hole.coords)
    return path


class NestingPieceItem(QGraphicsPathItem):
    def __init__(self, placement: Placement, parent_widget: "NestingRollWidget"):
        super().__init__()
        self.placement = placement
        self.parent_widget = parent_widget
        self.setPath(polygon_to_qpath(placement.placed_polygon, invert_y=False))
        self.setPen(QPen(QColor("#82c3ff"), 1.0))
        self.setBrush(QBrush(QColor(80, 160, 220, 80)))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self._drag_start = QPointF()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.parent_widget.view.setFocus()
        self._drag_start = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        new_pos = self.pos()
        dx = float(new_pos.x() - self._drag_start.x())
        dy = float(new_pos.y() - self._drag_start.y())
        dx, dy = self.parent_widget.snap_delta(self, dx, dy)
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            self.setPos(0.0, 0.0)
            return
        self.setPos(self._drag_start.x() + dx, self._drag_start.y() + dy)
        if not self.parent_widget.validate_move(self, dx, dy):
            self.setPos(self._drag_start)
            self.parent_widget.log("Move rejected: collision or outside roll bounds.")
            return
        self.parent_widget.apply_move(self, dx, dy)
        self.parent_widget.log(f"Piece nudged: {self.placement.piece.name}")


class NestingRollWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.roll_width_mm = 2500.0
        self.max_sheet_length_mm = 10000.0
        self.gap_mm = 20.0
        self.current_sheet = 0
        self.placements_by_sheet: Dict[int, List[Placement]] = {}
        self.items: List[NestingPieceItem] = []
        self.grid_items: List[QGraphicsItem] = []
        self.snap_enabled = True
        self.snap_grid_mm = 10.0
        self.nudge_step_mm = 5.0
        self.show_grid = True
        self._logger = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.title = QLabel("Fabric Roll View", self)
        self.title.setStyleSheet("font-size:14px; font-weight:600; color:#cfd7e3;")
        layout.addWidget(self.title)

        self.scene = QGraphicsScene(self)
        self.view = CadGraphicsView(self.scene, self)
        self.view.set_key_nudge_callback(self._handle_key_nudge)
        layout.addWidget(self.view, 1)

        self.info = QLabel("Run Optimize Nesting to populate roll layout.", self)
        self.info.setStyleSheet("color:#93a0b5;")
        layout.addWidget(self.info)

        self.roll_rect_item = QGraphicsRectItem()
        self.roll_rect_item.setPen(QPen(QColor("#5d6470"), 1.2))
        self.roll_rect_item.setBrush(QBrush(QColor(35, 38, 45, 30)))
        self.scene.addItem(self.roll_rect_item)

    def set_logger(self, logger):
        self._logger = logger

    def log(self, message: str):
        if self._logger:
            self._logger(message)

    def load_layout(
        self,
        placements_by_sheet: Dict[int, List[Placement]],
        roll_width_mm: float,
        max_sheet_length_mm: float,
        gap_mm: float,
    ) -> None:
        self.placements_by_sheet = placements_by_sheet
        self.roll_width_mm = float(roll_width_mm)
        self.max_sheet_length_mm = float(max_sheet_length_mm)
        self.gap_mm = float(gap_mm)
        self.current_sheet = 0
        self.render_sheet(0)

    def render_sheet(self, sheet_index: int) -> None:
        self.current_sheet = sheet_index
        for item in self.items:
            self.scene.removeItem(item)
        self.items = []
        for g in self.grid_items:
            self.scene.removeItem(g)
        self.grid_items = []

        self.roll_rect_item.setRect(0.0, 0.0, self.roll_width_mm, self.max_sheet_length_mm)
        self.roll_rect_item.setZValue(-100)
        self._draw_grid()

        placements = self.placements_by_sheet.get(sheet_index, [])
        for pl in placements:
            item = NestingPieceItem(pl, self)
            self.scene.addItem(item)
            self.items.append(item)

        self.scene.setSceneRect(self.roll_rect_item.rect().adjusted(-20, -20, 20, 20))
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.info.setText(f"Sheet {sheet_index + 1}: {len(placements)} piece(s). Drag to nudge.")

    def _with_clearance(self, poly: Polygon) -> Polygon:
        return poly.buffer(self.gap_mm * 0.5)

    def validate_move(self, moved_item: NestingPieceItem, dx: float, dy: float) -> bool:
        moved_poly = affinity.translate(moved_item.placement.placed_polygon, xoff=dx, yoff=dy)
        minx, miny, maxx, maxy = moved_poly.bounds
        if minx < 0 or miny < 0 or maxx > self.roll_width_mm or maxy > self.max_sheet_length_mm:
            return False
        moved_clear = self._with_clearance(moved_poly)
        for item in self.items:
            if item is moved_item:
                continue
            if moved_clear.intersects(self._with_clearance(item.placement.placed_polygon)):
                return False
        return True

    def apply_move(self, moved_item: NestingPieceItem, dx: float, dy: float) -> None:
        pl = moved_item.placement
        pl.insert_x += dx
        pl.insert_y += dy
        pl.placed_polygon = affinity.translate(pl.placed_polygon, xoff=dx, yoff=dy)
        moved_item.setPath(polygon_to_qpath(pl.placed_polygon, invert_y=False))
        moved_item.setPos(0.0, 0.0)

    def set_edit_options(self, snap_enabled: bool, snap_grid_mm: float, nudge_step_mm: float, show_grid: bool) -> None:
        self.snap_enabled = bool(snap_enabled)
        self.snap_grid_mm = max(1.0, float(snap_grid_mm))
        self.nudge_step_mm = max(0.1, float(nudge_step_mm))
        self.show_grid = bool(show_grid)
        self.render_sheet(self.current_sheet)

    def snap_delta(self, moved_item: NestingPieceItem, dx: float, dy: float) -> Tuple[float, float]:
        if not self.snap_enabled:
            return dx, dy
        pl = moved_item.placement
        tx = pl.insert_x + dx
        ty = pl.insert_y + dy
        gx = self.snap_grid_mm
        sx = round(tx / gx) * gx
        sy = round(ty / gx) * gx
        return float(sx - pl.insert_x), float(sy - pl.insert_y)

    def _draw_grid(self) -> None:
        if not self.show_grid:
            return
        spacing = max(10.0, self.snap_grid_mm)
        pen = QPen(QColor(88, 96, 112, 85), 0.0)
        x = 0.0
        while x <= self.roll_width_mm + 1e-9:
            line = self.scene.addLine(x, 0.0, x, self.max_sheet_length_mm, pen)
            line.setZValue(-99)
            self.grid_items.append(line)
            x += spacing
        y = 0.0
        while y <= self.max_sheet_length_mm + 1e-9:
            line = self.scene.addLine(0.0, y, self.roll_width_mm, y, pen)
            line.setZValue(-99)
            self.grid_items.append(line)
            y += spacing

    def _handle_key_nudge(self, step_x: int, step_y: int) -> None:
        selected = [it for it in self.items if it.isSelected()]
        if not selected:
            return
        if len(selected) > 1:
            self.log("Select one piece for keyboard nudge.")
            return
        item = selected[0]
        dx = float(step_x) * self.nudge_step_mm
        dy = float(step_y) * self.nudge_step_mm
        dx, dy = self.snap_delta(item, dx, dy)
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        if not self.validate_move(item, dx, dy):
            self.log("Nudge rejected: collision or outside roll bounds.")
            return
        self.apply_move(item, dx, dy)
        self.log(f"Piece nudged by keyboard: {item.placement.piece.name}")


class CompassGizmoWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(100, 100)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(16, 18, 22, 175); border: 1px solid #3b4350; border-radius: 8px;")
        self._hotspots: List[Tuple[str, QRectF]] = []
        self._on_view_selected = None

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(132, 132)

    def set_view_callback(self, callback) -> None:
        self._on_view_selected = callback

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() * 0.52, self.height() * 0.56
        s = 28.0

        top = QPolygonF([
            QPointF(cx, cy - s * 0.9),
            QPointF(cx + s, cy - s * 0.3),
            QPointF(cx, cy + s * 0.3),
            QPointF(cx - s, cy - s * 0.3),
        ])
        left = QPolygonF([
            QPointF(cx - s, cy - s * 0.3),
            QPointF(cx, cy + s * 0.3),
            QPointF(cx, cy + s * 1.2),
            QPointF(cx - s, cy + s * 0.6),
        ])
        right = QPolygonF([
            QPointF(cx + s, cy - s * 0.3),
            QPointF(cx, cy + s * 0.3),
            QPointF(cx, cy + s * 1.2),
            QPointF(cx + s, cy + s * 0.6),
        ])

        p.setPen(QPen(QColor("#8fa5c5"), 1.2))
        p.setBrush(QBrush(QColor(73, 96, 128, 180)))
        p.drawPolygon(top)
        p.setBrush(QBrush(QColor(52, 74, 102, 185)))
        p.drawPolygon(left)
        p.setBrush(QBrush(QColor(40, 60, 88, 190)))
        p.drawPolygon(right)

        p.setPen(QColor("#d7e2f3"))
        p.drawText(QPointF(cx - 5, cy - s * 0.48), "U")
        p.drawText(QPointF(cx - s * 0.68, cy + s * 0.2), "W")
        p.drawText(QPointF(cx + s * 0.42, cy + s * 0.2), "E")
        p.drawText(QPointF(cx - 5, cy + s * 0.86), "S")
        p.drawText(QPointF(cx - 5, cy + s * 1.35), "N")

        marker_pen = QPen(QColor("#9bb0ce"), 1.0)
        p.setPen(marker_pen)
        p.setBrush(QBrush(QColor(105, 128, 160, 180)))
        pts = {
            "TOP": QPointF(cx, cy - s * 1.05),
            "BOTTOM": QPointF(cx, cy + s * 1.35),
            "NORTH": QPointF(cx, cy + s * 1.0),
            "SOUTH": QPointF(cx, cy + s * 0.45),
            "EAST": QPointF(cx + s * 1.1, cy + s * 0.15),
            "WEST": QPointF(cx - s * 1.1, cy + s * 0.15),
            "ISO_NE": QPointF(cx + s * 0.78, cy - s * 0.65),
            "ISO_NW": QPointF(cx - s * 0.78, cy - s * 0.65),
            "ISO_SE": QPointF(cx + s * 0.95, cy + s * 0.85),
            "ISO_SW": QPointF(cx - s * 0.95, cy + s * 0.85),
        }
        self._hotspots = []
        r = 8.5
        for name, pt in pts.items():
            rect = QRectF(pt.x() - r, pt.y() - r, 2 * r, 2 * r)
            p.drawEllipse(rect)
            self._hotspots.append((name, rect))
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pt = event.position()
        for name, rect in self._hotspots:
            if rect.contains(pt):
                if self._on_view_selected:
                    self._on_view_selected(name)
                event.accept()
                return
        super().mousePressEvent(event)


class ThreeDViewportWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._on_drop_file = None
        self._on_flatten_surface = None
        self._mesh_name = ""
        self._mesh_vertices: np.ndarray | None = None
        self._mesh_faces: np.ndarray | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.fig = Figure(figsize=(7, 5), facecolor="#22252b")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.ax.set_facecolor("#22252b")
        self.ax.set_axis_off()
        layout.addWidget(self.canvas, 1)

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
        self.compass = CompassGizmoWidget(self)
        self.compass.set_view_callback(self._set_view_from_gizmo)
        self.compass.show()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())
        self.dim_label.raise_()
        margin = 14
        self.compass.move(self.width() - self.compass.width() - margin, margin)
        self.compass.raise_()

    def set_callbacks(self, on_drop_file, on_flatten_surface) -> None:
        self._on_drop_file = on_drop_file
        self._on_flatten_surface = on_flatten_surface

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
        if not urls:
            return
        path = urls[0].toLocalFile()
        if self._on_drop_file:
            self._on_drop_file(path)
        event.acceptProposedAction()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        if self._mesh_vertices is None or self._mesh_faces is None:
            return
        menu = QMenu(self)
        flatten_action = menu.addAction("Flatten This Surface")
        chosen = menu.exec(event.globalPos())
        if chosen == flatten_action and self._on_flatten_surface:
            self._on_flatten_surface()

    def clear_view(self) -> None:
        self._mesh_vertices = None
        self._mesh_faces = None
        self.ax.clear()
        self.ax.set_facecolor("#22252b")
        self.ax.set_axis_off()
        self.canvas.draw_idle()
        self.overlay.show()
        self.dim_label.setText("")

    def set_mesh(self, name: str, vertices: np.ndarray, faces: np.ndarray, dims_mm: Tuple[float, float, float]) -> None:
        self._mesh_name = name
        self._mesh_vertices = vertices
        self._mesh_faces = faces
        self.overlay.hide()
        self.ax.clear()
        self.ax.set_facecolor("#22252b")
        self.ax.set_axis_off()
        # Smooth shaded default, no wireframe-only look.
        self.ax.plot_trisurf(
            vertices[:, 0],
            vertices[:, 1],
            vertices[:, 2],
            triangles=faces,
            cmap="viridis",
            linewidth=0.05,
            edgecolor="none",
            antialiased=True,
            shade=True,
            alpha=0.95,
        )
        self._set_equal_axes(vertices)
        self.ax.view_init(elev=24, azim=-58)
        self.canvas.draw_idle()
        lx, ly, lz = dims_mm
        self.dim_label.setText(f"{name} | LxWxH: {lx:.1f} x {ly:.1f} x {lz:.1f} mm")

    def _set_equal_axes(self, vertices: np.ndarray) -> None:
        max_range = np.array([
            vertices[:, 0].max() - vertices[:, 0].min(),
            vertices[:, 1].max() - vertices[:, 1].min(),
            vertices[:, 2].max() - vertices[:, 2].min(),
        ]).max() / 2.0
        mid_x = (vertices[:, 0].max() + vertices[:, 0].min()) * 0.5
        mid_y = (vertices[:, 1].max() + vertices[:, 1].min()) * 0.5
        mid_z = (vertices[:, 2].max() + vertices[:, 2].min()) * 0.5
        self.ax.set_xlim(mid_x - max_range, mid_x + max_range)
        self.ax.set_ylim(mid_y - max_range, mid_y + max_range)
        self.ax.set_zlim(mid_z - max_range, mid_z + max_range)

    def _set_view_from_gizmo(self, preset: str) -> None:
        if self._mesh_vertices is None or self._mesh_faces is None:
            return
        mapping = {
            "TOP": (90, -90),
            "BOTTOM": (-90, -90),
            "NORTH": (0, -90),
            "SOUTH": (0, 90),
            "EAST": (0, 0),
            "WEST": (0, 180),
            "ISO_NE": (28, -45),
            "ISO_NW": (28, 135),
            "ISO_SE": (-20, -45),
            "ISO_SW": (-20, 135),
        }
        elev, azim = mapping.get(preset, (24, -58))
        self.ax.view_init(elev=elev, azim=azim)
        self.canvas.draw_idle()


class ThreeDXFlatMainWindow(QMainWindow):
    SETTINGS_ORG = "3DXFlat"
    SETTINGS_APP = "QtWorkspace"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("3DXFlat (Qt)")
        self.setMinimumSize(1100, 700)
        self._settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self._seam_debounce = QTimer(self)
        self._seam_debounce.setSingleShot(True)
        self._seam_debounce.setInterval(120)
        self._seam_debounce.timeout.connect(self._apply_seam_to_preview)

        self.loaded_model_path: str | None = None
        self.loaded_vertices: np.ndarray | None = None
        self.loaded_faces: np.ndarray | None = None
        self.loaded_mesh: trimesh.Trimesh | None = None
        self.last_export_path: str = str(self._settings.value("last_export_path", ""))
        self.last_output_dxf: str | None = None
        self.nesting_layout: Dict | None = None
        self.nesting_output_dir: str | None = None
        self._log_history: List[str] = []

        self.breadcrumb = BreadcrumbBar(self)
        self.breadcrumb.bind_step_handlers(self.on_breadcrumb_step)

        self._pages = QStackedWidget(self)
        self.page_import = QLabel("Import a model to begin.")
        self.page_import.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_import.setStyleSheet("font-size:22px;color:#b7c0cf;")
        self._pages.addWidget(self.page_import)

        self.flatten_workspace = QWidget(self)
        split_layout = QVBoxLayout(self.flatten_workspace)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(0)
        self.viewport_splitter = QSplitter(Qt.Orientation.Horizontal, self.flatten_workspace)
        self.viewport_splitter.setChildrenCollapsible(False)
        self.viewport_splitter.setHandleWidth(6)
        self.viewport_splitter.setContentsMargins(0, 0, 0, 0)
        self.viewport_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.viewport_splitter.setStyleSheet("QSplitter::handle { background-color: #353535; }")
        self.viewport3d = ThreeDViewportWidget(self.viewport_splitter)
        self.viewport3d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.viewport3d.set_callbacks(self.load_model_file, self.flatten_all)
        self.preview2d = Flatten2DPreviewWidget(self.viewport_splitter)
        self.preview2d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.viewport_splitter.addWidget(self.viewport3d)
        self.viewport_splitter.addWidget(self.preview2d)
        self.viewport_splitter.setStretchFactor(0, 10)
        self.viewport_splitter.setStretchFactor(1, 4)
        split_layout.addWidget(self.viewport_splitter, 1)
        self._preview2d_visible = False
        self._set_2d_preview_visible(False)
        self._pages.addWidget(self.flatten_workspace)

        self.page_nest = QWidget(self)
        nest_layout = QVBoxLayout(self.page_nest)
        nest_layout.setContentsMargins(8, 8, 8, 8)
        nest_layout.setSpacing(8)
        nav_row = QHBoxLayout()
        self.nest_prev_btn = QPushButton("Previous Sheet", self.page_nest)
        self.nest_next_btn = QPushButton("Next Sheet", self.page_nest)
        self.nest_sheet_label = QLabel("Sheet: -", self.page_nest)
        self.nest_prev_btn.clicked.connect(self.show_prev_nest_sheet)
        self.nest_next_btn.clicked.connect(self.show_next_nest_sheet)
        nav_row.addWidget(self.nest_prev_btn)
        nav_row.addWidget(self.nest_next_btn)
        nav_row.addWidget(self.nest_sheet_label)
        nav_row.addStretch(1)
        nest_layout.addLayout(nav_row)
        self.nesting_roll = NestingRollWidget(self.page_nest)
        self.nesting_roll.set_logger(self.log)
        nest_layout.addWidget(self.nesting_roll, 1)
        self._pages.addWidget(self.page_nest)

        self.page_export = QLabel("Export stage ready.")
        self.page_export.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_export.setStyleSheet("font-size:18px;color:#b7c0cf;")
        self._pages.addWidget(self.page_export)

        central = QWidget(self)
        c_layout = QVBoxLayout(central)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(0)
        c_layout.addWidget(self.breadcrumb, 0)
        workspace = QWidget(central)
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._pages, 1)
        self.guided_sidebar = self._build_guided_sidebar()
        self.guided_sidebar.setFixedWidth(380)
        workspace_layout.addWidget(self.guided_sidebar)
        c_layout.addWidget(workspace, 1)
        c_layout.setStretch(0, 0)
        c_layout.setStretch(1, 10)
        self.setCentralWidget(central)

        self._build_top_toolbar()
        self._add_view_actions()
        self._apply_nesting_edit_options()
        self._restore_layout()
        self.log("Qt UX mode initialized. Tk fallback still available.")

    def _build_top_toolbar(self) -> None:
        tb = QToolBar("Main Actions", self)
        tb.setMovable(False)
        tb.setIconSize(tb.iconSize())
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        import_action = QAction("Import 3D", self)
        import_action.triggered.connect(self.import_3d_dialog)
        tb.addAction(import_action)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        flatten_action = QAction("Flatten All", self)
        flatten_action.triggered.connect(self.flatten_all)
        tb.addAction(flatten_action)

        self.toggle_preview_action = QAction("Show/Hide 2D Preview", self)
        self.toggle_preview_action.triggered.connect(self.toggle_2d_preview)
        tb.addAction(self.toggle_preview_action)

        spacer2 = QWidget(self)
        spacer2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer2)

        export_action = QAction("Export DXF", self)
        export_action.triggered.connect(self.export_dxf)
        tb.addAction(export_action)

    def _set_2d_preview_visible(self, visible: bool) -> None:
        self._preview2d_visible = bool(visible)
        if self._preview2d_visible:
            self.preview2d.show()
            total = max(self.viewport_splitter.width(), 1200)
            left = int(total * 0.68)
            self.viewport_splitter.setSizes([left, total - left])
        else:
            self.preview2d.hide()
            self.viewport_splitter.setSizes([1, 0])

    def toggle_2d_preview(self) -> None:
        self._set_2d_preview_visible(not self._preview2d_visible)

    def _build_guided_sidebar(self) -> QWidget:
        host = QWidget(self)
        v = QVBoxLayout(host)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # Step 1
        step1 = QGroupBox("Step 1: Geometry", host)
        f1 = QFormLayout(step1)
        self.file_info_label = QLabel("No model loaded")
        self.file_info_label.setWordWrap(True)
        f1.addRow("File", self.file_info_label)
        self.units_combo = QComboBox(step1)
        self.units_combo.addItems(["mm", "cm", "m", "inch"])
        self.units_combo.setCurrentText("mm")
        self.units_combo.currentTextChanged.connect(self._update_dimensions_overlay)
        f1.addRow("Input Units", self.units_combo)
        self.scale_check_label = QLabel("LxWxH: -")
        f1.addRow("Scale Check", self.scale_check_label)
        self.mesh_quality_label = QLabel("Mesh Quality: -")
        self.mesh_quality_label.setWordWrap(True)
        f1.addRow("Mesh Check", self.mesh_quality_label)
        v.addWidget(step1)

        # Step 2
        step2 = QGroupBox("Step 2: Flattening", host)
        f2 = QFormLayout(step2)
        self.method_combo = QComboBox(step2)
        self.method_combo.addItems(["ARAP", "LSCM"])
        self.method_combo.setCurrentText("ARAP")
        f2.addRow("Method", self.method_combo)
        seam_wrap = QWidget(step2)
        seam_layout = QHBoxLayout(seam_wrap)
        seam_layout.setContentsMargins(0, 0, 0, 0)
        self.seam_slider = QSlider(Qt.Orientation.Horizontal, seam_wrap)
        self.seam_slider.setRange(0, 200)
        self.seam_slider.setValue(12)
        self.seam_spin = QSpinBox(seam_wrap)
        self.seam_spin.setRange(0, 200)
        self.seam_spin.setValue(12)
        seam_layout.addWidget(self.seam_slider, 1)
        seam_layout.addWidget(self.seam_spin)
        f2.addRow("Seam Allowance (mm)", seam_wrap)
        self.heatmap_check = QCheckBox("Show Strain Heatmap", step2)
        self.heatmap_check.setChecked(True)
        f2.addRow("", self.heatmap_check)
        v.addWidget(step2)

        # Step 3
        step3 = QGroupBox("Step 3: Nesting", host)
        f3 = QFormLayout(step3)
        self.roll_width_spin = QSpinBox(step3)
        self.roll_width_spin.setRange(500, 10000)
        self.roll_width_spin.setValue(2500)
        f3.addRow("Roll Width (mm)", self.roll_width_spin)
        self.gap_spin = QSpinBox(step3)
        self.gap_spin.setRange(0, 200)
        self.gap_spin.setValue(20)
        f3.addRow("Gap (mm)", self.gap_spin)
        self.snap_check = QCheckBox("Snap to Grid", step3)
        self.snap_check.setChecked(True)
        f3.addRow("", self.snap_check)
        self.snap_grid_spin = QSpinBox(step3)
        self.snap_grid_spin.setRange(1, 500)
        self.snap_grid_spin.setValue(10)
        f3.addRow("Grid Size (mm)", self.snap_grid_spin)
        self.show_grid_check = QCheckBox("Show Grid", step3)
        self.show_grid_check.setChecked(True)
        f3.addRow("", self.show_grid_check)
        self.nudge_step_spin = QSpinBox(step3)
        self.nudge_step_spin.setRange(1, 500)
        self.nudge_step_spin.setValue(5)
        f3.addRow("Nudge Step (mm)", self.nudge_step_spin)
        self.nest_button = QPushButton("Optimize Nesting", step3)
        self.nest_button.clicked.connect(self.run_nesting_job)
        f3.addRow("", self.nest_button)
        self.nest_export_button = QPushButton("Export Nested DXF", step3)
        self.nest_export_button.setEnabled(False)
        self.nest_export_button.clicked.connect(self.export_nested_layout)
        f3.addRow("", self.nest_export_button)
        v.addWidget(step3)

        # Step 4
        step4 = QGroupBox("Step 4: Output", host)
        f4 = QFormLayout(step4)
        self.layer_name_label = QLabel("CUT_LINE / FOLD_LINE / LABELS / RELIEF_CUT", step4)
        self.layer_name_label.setWordWrap(True)
        f4.addRow("Layers", self.layer_name_label)
        self.dxf_version_label = QLabel("AC1015 (R2000)", step4)
        f4.addRow("DXF Version", self.dxf_version_label)
        self.output_path_label = QLabel(self.last_export_path or "(last path not set)", step4)
        self.output_path_label.setWordWrap(True)
        f4.addRow("Last Export", self.output_path_label)
        v.addWidget(step4)
        v.addStretch(1)

        self.seam_slider.valueChanged.connect(self._on_seam_slider_changed)
        self.seam_spin.valueChanged.connect(self._on_seam_spin_changed)
        self.snap_check.toggled.connect(self._apply_nesting_edit_options)
        self.snap_grid_spin.valueChanged.connect(self._apply_nesting_edit_options)
        self.show_grid_check.toggled.connect(self._apply_nesting_edit_options)
        self.nudge_step_spin.valueChanged.connect(self._apply_nesting_edit_options)
        return host

    def _add_view_actions(self) -> None:
        view_menu = self.menuBar().addMenu("View")
        reset_layout = QAction("Reset Layout", self)
        reset_layout.triggered.connect(self._reset_layout)
        view_menu.addAction(reset_layout)

    def _reset_layout(self) -> None:
        self.guided_sidebar.show()
        self.log("Layout reset.")

    def on_breadcrumb_step(self, step: int) -> None:
        self.breadcrumb.set_step(step)
        self._pages.setCurrentIndex(step)
        self.log(f"Workflow step selected: {step + 1}")

    def import_3d_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import 3D Model", "", "3D files (*.stl *.obj *.stp *.step)")
        if path:
            self.load_model_file(path)

    def load_model_file(self, path: str) -> None:
        try:
            t0 = time.perf_counter()
            mesh = load_mesh_file(path)
            if isinstance(mesh, trimesh.Scene):
                mesh = mesh.dump(concatenate=True)
            vertices = np.asarray(mesh.vertices, dtype=np.float64)
            faces = np.asarray(mesh.faces, dtype=np.int64)
            if len(vertices) == 0 or len(faces) == 0:
                raise ValueError("Model has no valid triangles.")
            self.loaded_model_path = path
            self.loaded_vertices = vertices
            self.loaded_faces = faces
            self.loaded_mesh = mesh

            self.file_info_label.setText(Path(path).name)
            self._update_dimensions_overlay()
            dims = self._dims_in_mm(vertices)
            self.viewport3d.set_mesh(Path(path).name, vertices, faces, dims)
            self._update_mesh_quality()
            self.breadcrumb.set_step(1)
            self._pages.setCurrentIndex(1)
            dt = (time.perf_counter() - t0) * 1000.0
            self.log(f"INFO | Model loaded: {Path(path).name} ({len(vertices)} verts, {len(faces)} faces) in {dt:.0f} ms")
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))
            self.log(f"ERROR | Load error: {exc}")

    def _dims_in_mm(self, vertices: np.ndarray) -> Tuple[float, float, float]:
        scale = get_unit_scale(self.units_combo.currentText())
        ext = (vertices.max(axis=0) - vertices.min(axis=0)) * scale
        return float(ext[0]), float(ext[1]), float(ext[2])

    def _update_dimensions_overlay(self) -> None:
        if self.loaded_vertices is None:
            self.scale_check_label.setText("LxWxH: -")
            return
        lx, ly, lz = self._dims_in_mm(self.loaded_vertices)
        text = f"{lx:.1f} x {ly:.1f} x {lz:.1f} mm"
        self.scale_check_label.setText(text)
        if self.loaded_model_path:
            self.viewport3d.set_mesh(Path(self.loaded_model_path).name, self.loaded_vertices, self.loaded_faces, (lx, ly, lz))

    def flatten_all(self) -> None:
        if self.loaded_vertices is None or self.loaded_faces is None:
            QMessageBox.information(self, "Flatten", "Load a 3D model first.")
            return
        try:
            t0 = time.perf_counter()
            tmp = Path(tempfile.gettempdir()) / "3dxflat_qt_preview.dxf"
            method = self.method_combo.currentText()
            seam = float(self.seam_spin.value())
            flatten_mesh(
                vertices=self.loaded_vertices,
                faces=self.loaded_faces,
                path_output=str(tmp),
                show_plot=False,
                input_unit=self.units_combo.currentText(),
                method=method,
                boundary_mode="outer_only",
                seam_allowance_mm=seam,
                align_to_x=False,
                label_text=Path(self.loaded_model_path).stem if self.loaded_model_path else "panel",
                auto_relief_cut=True,
                relief_threshold_pct=3.0,
            )
            self.last_output_dxf = str(tmp)
            fold_poly = self._read_fold_polygon_from_dxf(str(tmp))
            self.preview2d.set_fold_polygon(fold_poly, fit=True)
            self.breadcrumb.set_step(2)
            self._pages.setCurrentIndex(1)
            dt = time.perf_counter() - t0
            self.log(f"INFO | Flatten complete ({method}) in {dt:.2f}s. Preview updated.")
        except Exception as exc:
            QMessageBox.critical(self, "Flatten Error", str(exc))
            self.log(f"ERROR | Flatten error: {exc}")

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

    def export_dxf(self) -> None:
        if self.loaded_vertices is None or self.loaded_faces is None:
            QMessageBox.information(self, "Export", "Load a 3D model first.")
            return
        path = self.last_export_path
        if not path:
            chosen, _ = QFileDialog.getSaveFileName(self, "Export Production DXF", "", "DXF files (*.dxf)")
            if not chosen:
                return
            path = chosen
            self.last_export_path = path
            self._settings.setValue("last_export_path", path)
            self.output_path_label.setText(path)

        try:
            t0 = time.perf_counter()
            flatten_mesh(
                vertices=self.loaded_vertices,
                faces=self.loaded_faces,
                path_output=path,
                show_plot=False,
                input_unit=self.units_combo.currentText(),
                method=self.method_combo.currentText(),
                boundary_mode="outer_only",
                seam_allowance_mm=float(self.seam_spin.value()),
                align_to_x=False,
                label_text=Path(self.loaded_model_path).stem if self.loaded_model_path else "panel",
                auto_relief_cut=True,
                relief_threshold_pct=3.0,
            )
            self.breadcrumb.set_step(3)
            dt = time.perf_counter() - t0
            self.log(f"INFO | Exported DXF: {Path(path).name} in {dt:.2f}s")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
            self.log(f"ERROR | Export error: {exc}")

    def run_nesting_job(self) -> None:
        try:
            if not self.last_export_path:
                raise ValueError("Export at least one DXF first to seed output path.")
            t0 = time.perf_counter()
            folder = str(Path(self.last_export_path).parent)
            self.nesting_layout = build_nesting_layout(
                input_dir=folder,
                roll_width_mm=float(self.roll_width_spin.value()),
                gap_mm=float(self.gap_spin.value()),
                rotation_step_deg=15.0,
                max_sheet_length_mm=10000.0,
            )
            self.nesting_output_dir = folder
            self.nesting_roll.load_layout(
                placements_by_sheet=self.nesting_layout["placements_by_sheet"],
                roll_width_mm=float(self.nesting_layout["roll_width_mm"]),
                max_sheet_length_mm=float(self.nesting_layout["max_sheet_length_mm"]),
                gap_mm=float(self.nesting_layout["gap_mm"]),
            )
            self._apply_nesting_edit_options()
            self.nest_export_button.setEnabled(True)
            self.breadcrumb.set_step(2)
            self._pages.setCurrentIndex(2)
            self._update_sheet_nav_state()
            dt = time.perf_counter() - t0
            self.log(f"INFO | Nesting layout ready: {self.nesting_layout.get('sheet_count')} sheet(s) in {dt:.2f}s")
        except Exception as exc:
            QMessageBox.warning(self, "Nesting", str(exc))
            self.log(f"ERROR | Nesting error: {exc}")

    def export_nested_layout(self) -> None:
        try:
            if not self.nesting_layout or not self.nesting_output_dir:
                raise ValueError("Run Optimize Nesting first.")
            t0 = time.perf_counter()
            files = export_nesting_layout(
                output_dir=self.nesting_output_dir,
                placements_by_sheet=self.nesting_layout["placements_by_sheet"],
            )
            self.breadcrumb.set_step(3)
            self._pages.setCurrentIndex(3)
            if len(files) == 1:
                self.log(f"INFO | Nested roll exported: {Path(files[0]).name}")
            else:
                self.log(f"INFO | Nested roll exported: {len(files)} sheet files")
            dt = time.perf_counter() - t0
            self.log(f"INFO | Nested export complete in {dt:.2f}s")
        except Exception as exc:
            QMessageBox.warning(self, "Nested Export", str(exc))
            self.log(f"ERROR | Nested export error: {exc}")

    def _sheet_count(self) -> int:
        if not self.nesting_layout:
            return 0
        return len(self.nesting_layout.get("placements_by_sheet", {}))

    def _update_sheet_nav_state(self) -> None:
        count = self._sheet_count()
        idx = self.nesting_roll.current_sheet
        self.nest_prev_btn.setEnabled(count > 1 and idx > 0)
        self.nest_next_btn.setEnabled(count > 1 and idx < count - 1)
        if count == 0:
            self.nest_sheet_label.setText("Sheet: -")
        else:
            self.nest_sheet_label.setText(f"Sheet: {idx + 1} / {count}")

    def show_prev_nest_sheet(self) -> None:
        count = self._sheet_count()
        if count <= 1:
            return
        idx = max(0, self.nesting_roll.current_sheet - 1)
        self.nesting_roll.render_sheet(idx)
        self._update_sheet_nav_state()

    def show_next_nest_sheet(self) -> None:
        count = self._sheet_count()
        if count <= 1:
            return
        idx = min(count - 1, self.nesting_roll.current_sheet + 1)
        self.nesting_roll.render_sheet(idx)
        self._update_sheet_nav_state()

    def _on_seam_slider_changed(self, value: int) -> None:
        if self.seam_spin.value() != value:
            self.seam_spin.blockSignals(True)
            self.seam_spin.setValue(value)
            self.seam_spin.blockSignals(False)
        self._seam_debounce.start()

    def _on_seam_spin_changed(self, value: int) -> None:
        if self.seam_slider.value() != value:
            self.seam_slider.blockSignals(True)
            self.seam_slider.setValue(value)
            self.seam_slider.blockSignals(False)
        self._seam_debounce.start()

    def _apply_seam_to_preview(self) -> None:
        self.preview2d.set_seam(float(self.seam_spin.value()))
        self.log(f"INFO | Seam preview updated: {self.seam_spin.value()} mm")

    def _apply_nesting_edit_options(self) -> None:
        if not hasattr(self, "nesting_roll"):
            return
        self.nesting_roll.set_edit_options(
            snap_enabled=bool(self.snap_check.isChecked()),
            snap_grid_mm=float(self.snap_grid_spin.value()),
            nudge_step_mm=float(self.nudge_step_spin.value()),
            show_grid=bool(self.show_grid_check.isChecked()),
        )

    def log(self, message: str) -> None:
        self._log_history.append(message)
        self.statusBar().showMessage(message, 5000)

    def _update_mesh_quality(self) -> None:
        if self.loaded_mesh is None:
            self.mesh_quality_label.setText("Mesh Quality: -")
            return
        mesh = self.loaded_mesh
        edges_sorted = np.sort(mesh.edges_sorted, axis=1)
        _, edge_use_counts = np.unique(edges_sorted, axis=0, return_counts=True)
        open_edges = int(np.sum(edge_use_counts == 1))
        non_manifold_edges = int(np.sum(edge_use_counts > 2))
        degenerate = int(np.sum(mesh.area_faces <= 1e-12))

        if non_manifold_edges > 0:
            quality = f"WARNING: non-manifold={non_manifold_edges}, open={open_edges}, degenerate={degenerate}"
            self.log("WARNING | Non-manifold edges detected. Clean mesh before production export.")
        elif open_edges > 0:
            quality = f"Open shell: non-manifold=0, open={open_edges}, degenerate={degenerate}"
            self.log("INFO | Open edges detected (sheet-like geometry may be expected for panel workflows).")
        else:
            quality = f"Closed/clean: non-manifold=0, open=0, degenerate={degenerate}"
            self.log("INFO | Mesh quality check passed.")
        self.mesh_quality_label.setText(quality)

    def closeEvent(self, event) -> None:  # noqa: N802
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


def run_qt_app() -> int:
    from PySide6.QtGui import QFont, QSurfaceFormat

    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setVersion(4, 1)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication.instance() or QApplication(sys.argv)

    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(
        """
        QMainWindow { background-color: #252525; color: #e0e0e0; }
        QWidget { background-color: #252525; color: #e0e0e0; }
        QToolBar { background: #252525; border: 1px solid #3a3a3a; spacing: 8px; }
        QStatusBar { background-color: #252525; color: #888; font-size: 11px; }
        QStatusBar QLabel { color: #a7b2c2; background: transparent; }

        QTabWidget::pane { border: 1px solid #333; top: -1px; background-color: #252525; }
        QTabBar::tab {
            background: #252525;
            padding: 10px 20px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            margin-right: 2px;
        }
        QTabBar::tab:selected { background: #444; color: #00aaff; border-bottom: 2px solid #00aaff; }

        QPushButton, QToolButton {
            background-color: #252525;
            border: 1px solid #555;
            padding: 8px 15px;
            border-radius: 4px;
            min-width: 80px;
        }
        QPushButton:hover, QToolButton:hover { background-color: #252525; border: 1px solid #00aaff; }
        QPushButton:disabled, QToolButton:disabled { background-color: #252525; color: #8f8f8f; border-color: #4a4a4a; }
        QPushButton#FlattenButton, QToolButton#FlattenButton { background-color: #0066cc; font-weight: bold; font-size: 14px; }
        QPushButton#FlattenButton:hover, QToolButton#FlattenButton:hover { background-color: #0078d7; }

        QGroupBox {
            font-weight: bold;
            border: 1px solid #444;
            margin-top: 10px;
            padding-top: 15px;
            border-radius: 4px;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; color: #b9c6d7; }

        QLineEdit, QComboBox, QSpinBox, QTextEdit, QListWidget {
            background: #252525;
            border: 1px solid #4b5665;
            border-radius: 4px;
            padding: 6px;
        }
        QProgressBar {
            border: 1px solid #4c596d;
            border-radius: 4px;
            background: #252525;
            color: #dce7f7;
            text-align: center;
            padding: 1px;
        }
        QProgressBar::chunk { background-color: #0078d7; border-radius: 3px; }
        """
    )

    from qt_app.ribbon_window import create_window

    win = create_window()
    win.show()
    return app.exec()
