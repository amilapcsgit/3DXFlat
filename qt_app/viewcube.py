from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


class ViewCubeWidget(QWidget):
    faceClicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(140, 140)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: #252525; border: 1px solid #3b4350; border-radius: 8px;")
        self.setMouseTracking(True)
        self._elev = 24.0
        self._azim = -58.0
        self._rot = np.eye(3, dtype=np.float64)
        self._hover_face: str | None = None
        self._hotspots: Dict[str, QPolygonF] = {}
        self._nav_hotspots: List[Tuple[str, QPointF, float]] = []
        self._draw_order: List[str] = []
        self._rebuild_rotation_matrix()

    def set_rotation(self, elev: float, azim: float) -> None:
        if abs(self._elev - elev) < 0.1 and abs(self._azim - azim) < 0.1:
            return
        self._elev = float(elev)
        self._azim = float(azim)
        self._rebuild_rotation_matrix()
        self.update()

    def _rebuild_rotation_matrix(self) -> None:
        az = math.radians(self._azim)
        el = math.radians(self._elev)
        cz, sz = math.cos(az), math.sin(az)
        cx, sx = math.cos(el), math.sin(el)
        rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
        rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]], dtype=np.float64)
        self._rot = rx @ rz

    def _rotate(self, v: np.ndarray) -> np.ndarray:
        return (self._rot @ v.reshape(3, 1)).reshape(3)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx, cy = self.width() * 0.52, self.height() * 0.54
        scale = 26.0
        verts = {
            "ppp": np.array([1.0, 1.0, 1.0], dtype=np.float64),
            "ppm": np.array([1.0, 1.0, -1.0], dtype=np.float64),
            "pmp": np.array([1.0, -1.0, 1.0], dtype=np.float64),
            "pmm": np.array([1.0, -1.0, -1.0], dtype=np.float64),
            "mpp": np.array([-1.0, 1.0, 1.0], dtype=np.float64),
            "mpm": np.array([-1.0, 1.0, -1.0], dtype=np.float64),
            "mmp": np.array([-1.0, -1.0, 1.0], dtype=np.float64),
            "mmm": np.array([-1.0, -1.0, -1.0], dtype=np.float64),
        }
        faces = [
            ("TOP", ["mpp", "ppp", "pmp", "mmp"], QColor(105, 105, 105, 238), "TOP"),
            ("BOTTOM", ["mpm", "ppm", "pmm", "mmm"], QColor(58, 58, 58, 220), "BOT"),
            ("FRONT", ["mmp", "pmp", "pmm", "mmm"], QColor(85, 85, 85, 232), "F"),
            ("BACK", ["mpp", "ppp", "ppm", "mpm"], QColor(78, 78, 78, 228), "B"),
            ("RIGHT", ["ppp", "ppm", "pmm", "pmp"], QColor(74, 74, 74, 226), "R"),
            ("LEFT", ["mpp", "mpm", "mmm", "mmp"], QColor(92, 92, 92, 230), "L"),
        ]

        rverts = {k: self._rotate(v) for k, v in verts.items()}
        draw_faces: List[Tuple[float, str, QPolygonF, QColor, str]] = []
        for name, keys, color, label in faces:
            poly3 = [rverts[k] for k in keys]
            qpoly = QPolygonF([QPointF(cx + p3[0] * scale, cy - p3[1] * scale) for p3 in poly3])
            depth = float(np.mean([p3[2] for p3 in poly3]))
            draw_faces.append((depth, name, qpoly, color, label))

        draw_faces.sort(key=lambda x: x[0])
        self._hotspots = {}
        self._nav_hotspots = []
        self._draw_order = []
        p.setPen(QPen(QColor("#b5c7df"), 1.0))
        for depth, name, qpoly, color, label in draw_faces:
            col = QColor(color)
            if name == self._hover_face:
                col = col.lighter(132)
                col.setAlpha(246)
            elif depth < 0:
                col = col.darker(108)
                col.setAlpha(188)
            p.setBrush(col)
            p.drawPolygon(qpoly)
            ctr = qpoly.boundingRect().center()
            p.setPen(QPen(QColor("#ffffff"), 1.0))
            p.drawText(QPointF(ctr.x() - 7.0, ctr.y() + 4.0), label)
            p.setPen(QPen(QColor("#b5c7df"), 1.0))
            self._hotspots[name] = qpoly
            self._draw_order.append(name)

        p.setPen(QColor("#9fb0c7"))
        p.drawText(QPointF(10.0, 17.0), "View Cube")
        p.drawText(QPointF(10.0, self.height() - 10.0), "Click face/pad")

        ring_center = QPointF(cx, cy + scale * 2.05)
        ring_rx = scale * 1.05
        ring_ry = scale * 0.34
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#9a9a9a"), 1.25))
        p.drawEllipse(ring_center, ring_rx, ring_ry)
        p.setPen(QPen(QColor("#ffffff"), 1.0))
        p.drawText(QPointF(ring_center.x() - 4.0, ring_center.y() - ring_ry - 4.0), "N")
        p.drawText(QPointF(ring_center.x() - 3.0, ring_center.y() + ring_ry + 12.0), "S")

        # Explicit pads keep all six faces reliably clickable.
        nav = {
            "TOP": QPointF(cx, cy - scale * 1.85),
            "BOTTOM": QPointF(cx, cy + scale * 1.55),
            "LEFT": QPointF(cx - scale * 1.9, cy),
            "RIGHT": QPointF(cx + scale * 1.9, cy),
            "FRONT": QPointF(cx, cy + scale * 1.08),
            "BACK": QPointF(cx, cy - scale * 1.12),
        }
        for name, pos in nav.items():
            r = 8.0
            self._nav_hotspots.append((name, pos, r))
            active = self._hover_face == name
            p.setBrush(QColor(120, 120, 120, 240) if active else QColor(72, 72, 72, 225))
            p.setPen(QPen(QColor("#d6d6d6"), 1.0))
            p.drawEllipse(pos, r, r)
            lab = "D" if name == "BOTTOM" else ("B" if name == "BACK" else ("F" if name == "FRONT" else name[0]))
            p.setPen(QPen(QColor("#ffffff"), 1.0))
            p.drawText(QPointF(pos.x() - 3.0, pos.y() + 4.0), lab)
        p.end()

    def _face_from_hit_point(self, hit_point_obj: np.ndarray) -> str:
        axis = int(np.argmax(np.abs(hit_point_obj)))
        value = float(hit_point_obj[axis])
        if axis == 0:
            return "RIGHT" if value >= 0.0 else "LEFT"
        if axis == 1:
            return "BACK" if value >= 0.0 else "FRONT"
        return "TOP" if value >= 0.0 else "BOTTOM"

    def _ray_box_intersection_t(self, origin: np.ndarray, direction: np.ndarray) -> float | None:
        t_min = -float("inf")
        t_max = float("inf")
        eps = 1e-9
        for i in range(3):
            o = float(origin[i])
            d = float(direction[i])
            if abs(d) < eps:
                if o < -1.0 or o > 1.0:
                    return None
                continue
            t1 = (-1.0 - o) / d
            t2 = (1.0 - o) / d
            near = min(t1, t2)
            far = max(t1, t2)
            t_min = max(t_min, near)
            t_max = min(t_max, far)
            if t_min > t_max:
                return None
        t = t_min if t_min >= 0.0 else t_max
        return t if t >= 0.0 else None

    def _raycast_face(self, pt: QPointF) -> str | None:
        cx, cy = self.width() * 0.52, self.height() * 0.54
        scale = 26.0
        vx = (float(pt.x()) - cx) / scale
        vy = (cy - float(pt.y())) / scale

        rot_inv = self._rot.T
        for origin_z, dir_z in ((-6.0, 1.0), (6.0, -1.0)):
            origin_view = np.array([vx, vy, origin_z], dtype=np.float64)
            direction_view = np.array([0.0, 0.0, dir_z], dtype=np.float64)
            origin_obj = rot_inv @ origin_view
            direction_obj = rot_inv @ direction_view
            t = self._ray_box_intersection_t(origin_obj, direction_obj)
            if t is None:
                continue
            hit_obj = origin_obj + direction_obj * t
            return self._face_from_hit_point(hit_obj)
        return None

    def _face_at(self, pt: QPointF) -> str | None:
        for name, pos, r in self._nav_hotspots:
            dx = float(pt.x() - pos.x())
            dy = float(pt.y() - pos.y())
            if (dx * dx + dy * dy) <= (r * r):
                return name
        hit = self._raycast_face(pt)
        if hit is not None:
            return hit
        for name in reversed(self._draw_order):
            poly = self._hotspots.get(name)
            if poly is not None and poly.containsPoint(pt, Qt.FillRule.WindingFill):
                return name
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        face = self._face_at(event.position())
        if face != self._hover_face:
            self._hover_face = face
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_face = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            face = self._face_at(event.position())
            if face is not None:
                self.faceClicked.emit(face)
                event.accept()
                return
        super().mousePressEvent(event)
