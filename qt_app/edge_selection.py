from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np


Edge = Tuple[int, int]


def _norm_edge(edge: Sequence[int]) -> Edge:
    a = int(edge[0])
    b = int(edge[1])
    return (a, b) if a < b else (b, a)


def build_selected_submesh(faces: np.ndarray, selected_faces: Iterable[int]) -> Dict[str, np.ndarray]:
    """Build a compact submesh from a selected face id set.

    Returns:
      - face_ids_global: selected face ids in source mesh
      - vertex_ids_global: source vertex ids used by selected faces
      - faces_sub: selected faces with compact vertex indexing
    """
    faces = np.asarray(faces, dtype=np.int64)
    selected_ids = np.asarray(sorted({int(i) for i in selected_faces}), dtype=np.int64)
    if faces.ndim != 2 or (len(faces) and faces.shape[1] != 3):
        raise ValueError("faces must be Nx3.")
    if len(selected_ids) == 0:
        return {
            "face_ids_global": selected_ids,
            "vertex_ids_global": np.empty((0,), dtype=np.int64),
            "faces_sub": np.empty((0, 3), dtype=np.int64),
        }
    selected_ids = selected_ids[(selected_ids >= 0) & (selected_ids < len(faces))]
    if len(selected_ids) == 0:
        return {
            "face_ids_global": selected_ids,
            "vertex_ids_global": np.empty((0,), dtype=np.int64),
            "faces_sub": np.empty((0, 3), dtype=np.int64),
        }

    faces_sel = np.asarray(faces[selected_ids], dtype=np.int64)
    used_vertices = np.unique(faces_sel.reshape(-1))
    remap = {int(v): i for i, v in enumerate(used_vertices.tolist())}
    faces_sub = np.asarray([[remap[int(a)], remap[int(b)], remap[int(c)]] for a, b, c in faces_sel], dtype=np.int64)
    return {
        "face_ids_global": selected_ids,
        "vertex_ids_global": used_vertices.astype(np.int64),
        "faces_sub": faces_sub,
    }


def compute_patch_boundary_edges(faces_sub: np.ndarray) -> List[Edge]:
    faces_sub = np.asarray(faces_sub, dtype=np.int64)
    if faces_sub.ndim != 2 or (len(faces_sub) and faces_sub.shape[1] != 3):
        raise ValueError("faces_sub must be Nx3.")
    if len(faces_sub) == 0:
        return []
    edge_count: Dict[Edge, int] = defaultdict(int)
    for a, b, c in faces_sub:
        edge_count[_norm_edge((a, b))] += 1
        edge_count[_norm_edge((b, c))] += 1
        edge_count[_norm_edge((c, a))] += 1
    return sorted([e for e, c in edge_count.items() if c == 1])


def compute_feature_edges(faces_sub: np.ndarray, vertices_sub: np.ndarray, angle_thresh_deg: float) -> List[Edge]:
    faces_sub = np.asarray(faces_sub, dtype=np.int64)
    vertices_sub = np.asarray(vertices_sub, dtype=np.float64)
    if len(faces_sub) == 0:
        return []
    if faces_sub.ndim != 2 or faces_sub.shape[1] != 3:
        raise ValueError("faces_sub must be Nx3.")
    if vertices_sub.ndim != 2 or vertices_sub.shape[1] != 3:
        raise ValueError("vertices_sub must be Nx3.")

    tri = vertices_sub[faces_sub]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nl = np.linalg.norm(n, axis=1)
    nl = np.where(nl < 1e-12, 1e-12, nl)
    normals = n / nl[:, None]

    edge_faces: Dict[Edge, List[int]] = defaultdict(list)
    for fi, (a, b, c) in enumerate(faces_sub):
        edge_faces[_norm_edge((a, b))].append(int(fi))
        edge_faces[_norm_edge((b, c))].append(int(fi))
        edge_faces[_norm_edge((c, a))].append(int(fi))

    cos_thresh = float(np.cos(np.radians(float(angle_thresh_deg))))
    out: List[Edge] = []
    for edge, linked in edge_faces.items():
        if len(linked) == 1:
            out.append(edge)
            continue
        if len(linked) != 2:
            out.append(edge)
            continue
        a, b = linked
        cosang = float(np.clip(np.dot(normals[a], normals[b]), -1.0, 1.0))
        if cosang <= cos_thresh:
            out.append(edge)
    return sorted(set(out))


def _project_points_to_screen(
    vertices: np.ndarray,
    viewproj: np.ndarray,
    viewport_w: int,
    viewport_h: int,
) -> Tuple[np.ndarray, np.ndarray]:
    verts = np.asarray(vertices, dtype=np.float64)
    m = np.asarray(viewproj, dtype=np.float64)
    if m.shape != (4, 4):
        raise ValueError("viewproj must be 4x4.")
    if len(verts) == 0:
        return np.empty((0, 2), dtype=np.float64), np.empty((0,), dtype=bool)
    vh = np.ones((len(verts), 1), dtype=np.float64)
    clip = (m @ np.hstack([verts, vh]).T).T
    w = clip[:, 3]
    valid = np.abs(w) > 1e-12
    ndc = np.zeros((len(verts), 3), dtype=np.float64)
    ndc[valid] = clip[valid, :3] / w[valid][:, None]
    screen = np.empty((len(verts), 2), dtype=np.float64)
    vw = max(1, int(viewport_w))
    vh_px = max(1, int(viewport_h))
    screen[:, 0] = (ndc[:, 0] * 0.5 + 0.5) * float(vw)
    screen[:, 1] = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * float(vh_px)
    in_depth = (ndc[:, 2] >= -1.5) & (ndc[:, 2] <= 1.5)
    return screen, (valid & in_depth)


def _point_to_segment_distance_sq(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
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


def screen_space_pick_edge(
    mouse_xy: Sequence[float],
    edges: Iterable[Sequence[int]],
    vertices: np.ndarray,
    viewproj: np.ndarray,
    viewport_w: int,
    viewport_h: int,
    px_tol: float,
) -> Edge | None:
    edges_norm = [_norm_edge(e) for e in edges]
    if not edges_norm:
        return None
    screen_pts, valid = _project_points_to_screen(vertices, viewproj, viewport_w, viewport_h)
    p = np.asarray([float(mouse_xy[0]), float(mouse_xy[1])], dtype=np.float64)
    tol_sq = float(px_tol) * float(px_tol)
    best_edge = None
    best_d = float("inf")
    for edge in edges_norm:
        a, b = edge
        if a < 0 or b < 0 or a >= len(screen_pts) or b >= len(screen_pts):
            continue
        if not (bool(valid[a]) and bool(valid[b])):
            continue
        d = _point_to_segment_distance_sq(p, screen_pts[a], screen_pts[b])
        if d < best_d:
            best_d = d
            best_edge = edge
    if best_edge is None or best_d > tol_sq:
        return None
    return best_edge


def fallback_pick_edge_on_triangle(
    mouse_xy: Sequence[float],
    tri_edges_screen: Iterable[Sequence[object]],
    px_tol: float,
):
    """Pick nearest triangle edge from pre-projected screen segments.

    Each tri edge can be either:
      - ((x0, y0), (x1, y1), payload)
      - ((x0, y0), (x1, y1))
    """
    p = np.asarray([float(mouse_xy[0]), float(mouse_xy[1])], dtype=np.float64)
    tol_sq = float(px_tol) * float(px_tol)
    best_payload = None
    best_d = float("inf")
    for idx, edge in enumerate(tri_edges_screen):
        if len(edge) < 2:
            continue
        a = np.asarray(edge[0], dtype=np.float64)
        b = np.asarray(edge[1], dtype=np.float64)
        payload = edge[2] if len(edge) >= 3 else idx
        d = _point_to_segment_distance_sq(p, a, b)
        if d < best_d:
            best_d = d
            best_payload = payload
    if best_payload is None or best_d > tol_sq:
        return None
    return best_payload
