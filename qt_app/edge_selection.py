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


def _point_key3(point: Sequence[float], tol: float) -> Tuple[int, int, int]:
    p = np.asarray(point, dtype=np.float64)
    scale = max(float(tol), 1e-9)
    return (
        int(np.rint(p[0] / scale)),
        int(np.rint(p[1] / scale)),
        int(np.rint(p[2] / scale)),
    )


def _normalized_direction(vec: np.ndarray) -> np.ndarray | None:
    arr = np.asarray(vec, dtype=np.float64).reshape(-1)
    if arr.size != 3:
        return None
    n = float(np.linalg.norm(arr))
    if n <= 1e-12:
        return None
    return arr / n


def _polyline_endpoint_tangent(polyline: np.ndarray, *, at_start: bool) -> np.ndarray | None:
    poly = np.asarray(polyline, dtype=np.float64)
    if poly.ndim != 2 or poly.shape[1] != 3 or len(poly) < 2:
        return None
    if at_start:
        origin = np.asarray(poly[0], dtype=np.float64)
        for i in range(1, len(poly)):
            d = np.asarray(poly[i], dtype=np.float64) - origin
            out = _normalized_direction(d)
            if out is not None:
                return out
        return None
    origin = np.asarray(poly[-1], dtype=np.float64)
    for i in range(len(poly) - 2, -1, -1):
        d = np.asarray(poly[i], dtype=np.float64) - origin
        out = _normalized_direction(d)
        if out is not None:
            return out
    return None


def _tangent_continuity_ok(dir_a: np.ndarray | None, dir_b: np.ndarray | None, *, max_axis_angle_deg: float) -> bool:
    if dir_a is None or dir_b is None:
        return False
    dot = float(np.clip(np.dot(dir_a, dir_b), -1.0, 1.0))
    # Compare unoriented tangent axes (0 deg and 180 deg both considered continuous).
    axis_dot = abs(dot)
    axis_cos_min = float(np.cos(np.radians(max(0.0, min(90.0, float(max_axis_angle_deg))))))
    return axis_dot >= axis_cos_min


def build_edge_chains(
    edge_ids: Iterable[int],
    edge_polylines: Dict[int, np.ndarray],
    *,
    endpoint_tol: float = 1e-5,
    tangent_thresh_deg: float = 20.0,
) -> List[Tuple[int, ...]]:
    valid_edges: List[int] = []
    endpoints: Dict[int, Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = {}
    tangents: Dict[int, Tuple[np.ndarray | None, np.ndarray | None]] = {}

    for edge_id in sorted({int(x) for x in edge_ids}):
        poly = np.asarray(edge_polylines.get(int(edge_id), np.empty((0, 3))), dtype=np.float64)
        if poly.ndim != 2 or poly.shape[1] != 3 or len(poly) < 2:
            continue
        a = _point_key3(poly[0], endpoint_tol)
        b = _point_key3(poly[-1], endpoint_tol)
        endpoints[int(edge_id)] = (a, b)
        tangents[int(edge_id)] = (
            _polyline_endpoint_tangent(poly, at_start=True),
            _polyline_endpoint_tangent(poly, at_start=False),
        )
        valid_edges.append(int(edge_id))

    if not valid_edges:
        return []

    vertex_to_incidence: Dict[Tuple[int, int, int], List[Tuple[int, int]]] = defaultdict(list)
    edge_to_vertices: Dict[int, Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = {}
    for edge_id in valid_edges:
        v0, v1 = endpoints[edge_id]
        edge_to_vertices[edge_id] = (v0, v1)
        vertex_to_incidence[v0].append((edge_id, 0))
        vertex_to_incidence[v1].append((edge_id, 1))

    # Tangent-continuity graph over edges.
    edge_graph: Dict[int, set[int]] = {int(e): set() for e in valid_edges}
    for linked in vertex_to_incidence.values():
        if len(linked) < 2:
            continue
        for i in range(len(linked)):
            ea, enda = linked[i]
            da = tangents.get(int(ea), (None, None))[int(enda)]
            for j in range(i + 1, len(linked)):
                eb, endb = linked[j]
                db = tangents.get(int(eb), (None, None))[int(endb)]
                if _tangent_continuity_ok(da, db, max_axis_angle_deg=tangent_thresh_deg):
                    edge_graph[int(ea)].add(int(eb))
                    edge_graph[int(eb)].add(int(ea))

    # Connected components over edges.
    comps: List[List[int]] = []
    unseen = set(valid_edges)
    while unseen:
        start = min(unseen)
        stack = [start]
        unseen.discard(start)
        comp: List[int] = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in sorted(edge_graph.get(int(cur), ())):
                if nb in unseen:
                    unseen.discard(nb)
                    stack.append(nb)
        comps.append(sorted(comp))

    chains: List[Tuple[int, ...]] = []
    for comp in comps:
        if len(comp) == 1:
            chains.append((int(comp[0]),))
            continue

        comp_edges = set(comp)
        comp_vertex_to_edges: Dict[Tuple[int, int, int], List[int]] = defaultdict(list)
        for edge_id in comp:
            v0, v1 = edge_to_vertices[edge_id]
            comp_vertex_to_edges[v0].append(edge_id)
            comp_vertex_to_edges[v1].append(edge_id)

        degree1_vertices = sorted([v for v, linked in comp_vertex_to_edges.items() if len(linked) == 1])
        if degree1_vertices:
            start_vertex = degree1_vertices[0]
            start_edge = min(comp_vertex_to_edges[start_vertex])
        else:
            start_edge = min(comp)
            start_vertex = edge_to_vertices[start_edge][0]

        ordered: List[int] = [int(start_edge)]
        used_local = {int(start_edge)}
        v0, v1 = edge_to_vertices[start_edge]
        current_vertex = v1 if v0 == start_vertex else v0

        while True:
            candidates = [e for e in comp_vertex_to_edges[current_vertex] if e in comp_edges and e not in used_local]
            if len(candidates) != 1:
                break
            nxt = int(candidates[0])
            used_local.add(nxt)
            ordered.append(nxt)
            a, b = edge_to_vertices[nxt]
            current_vertex = b if a == current_vertex else a
            if len(used_local) == len(comp_edges):
                break

        if len(used_local) < len(comp_edges):
            # Branching topology: deterministic fallback (sorted IDs).
            chains.append(tuple(sorted(int(e) for e in comp)))
        else:
            chains.append(tuple(ordered))
    return sorted(chains, key=lambda c: (len(c), c))


def chain_length_from_polylines(chain: Sequence[int], edge_polylines: Dict[int, np.ndarray]) -> float:
    total = 0.0
    for edge_id in chain:
        poly = np.asarray(edge_polylines.get(int(edge_id), np.empty((0, 3))), dtype=np.float64)
        if poly.ndim != 2 or poly.shape[1] != 3 or len(poly) < 2:
            continue
        seg = poly[1:] - poly[:-1]
        total += float(np.sum(np.linalg.norm(seg, axis=1)))
    return float(total)


def _project_xyz_to_screen(points_xyz: np.ndarray, viewproj: np.ndarray, viewport_w: int, viewport_h: int) -> Tuple[np.ndarray, np.ndarray]:
    pts = np.asarray(points_xyz, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        return np.empty((0, 2), dtype=np.float64), np.empty((0,), dtype=bool)
    m = np.asarray(viewproj, dtype=np.float64)
    if m.shape != (4, 4):
        raise ValueError("viewproj must be 4x4.")
    if len(pts) == 0:
        return np.empty((0, 2), dtype=np.float64), np.empty((0,), dtype=bool)
    vh = np.ones((len(pts), 1), dtype=np.float64)
    clip = (m @ np.hstack([pts, vh]).T).T
    w = clip[:, 3]
    valid = np.abs(w) > 1e-12
    ndc = np.zeros((len(pts), 3), dtype=np.float64)
    ndc[valid] = clip[valid, :3] / w[valid][:, None]
    screen = np.empty((len(pts), 2), dtype=np.float64)
    vw = max(1, int(viewport_w))
    vh_px = max(1, int(viewport_h))
    screen[:, 0] = (ndc[:, 0] * 0.5 + 0.5) * float(vw)
    screen[:, 1] = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * float(vh_px)
    in_depth = (ndc[:, 2] >= -1.5) & (ndc[:, 2] <= 1.5)
    return screen, (valid & in_depth)


def screen_space_pick_polyline_chain(
    mouse_xy: Sequence[float],
    chains: Iterable[Sequence[int]],
    edge_polylines: Dict[int, np.ndarray],
    viewproj: np.ndarray,
    viewport_w: int,
    viewport_h: int,
    px_tol: float,
) -> Tuple[int, ...] | None:
    p = np.asarray([float(mouse_xy[0]), float(mouse_xy[1])], dtype=np.float64)
    tol_sq = float(px_tol) * float(px_tol)
    best_chain: Tuple[int, ...] | None = None
    best_dist = float("inf")

    for chain in chains:
        chain_tuple = tuple(int(x) for x in chain)
        chain_best = float("inf")
        for edge_id in chain_tuple:
            poly = np.asarray(edge_polylines.get(int(edge_id), np.empty((0, 3))), dtype=np.float64)
            if poly.ndim != 2 or poly.shape[1] != 3 or len(poly) < 2:
                continue
            screen, valid = _project_xyz_to_screen(poly, viewproj, viewport_w, viewport_h)
            for i in range(len(screen) - 1):
                if not (bool(valid[i]) and bool(valid[i + 1])):
                    continue
                d = _point_to_segment_distance_sq(p, screen[i], screen[i + 1])
                if d < chain_best:
                    chain_best = d
        if chain_best < best_dist:
            best_dist = chain_best
            best_chain = chain_tuple

    if best_chain is None or best_dist > tol_sq:
        return None
    return best_chain


def screen_space_pick_polyline_edge(
    mouse_xy: Sequence[float],
    edge_ids: Iterable[int],
    edge_polylines: Dict[int, np.ndarray],
    viewproj: np.ndarray,
    viewport_w: int,
    viewport_h: int,
    px_tol: float,
) -> int | None:
    p = np.asarray([float(mouse_xy[0]), float(mouse_xy[1])], dtype=np.float64)
    tol_sq = float(px_tol) * float(px_tol)
    best_edge: int | None = None
    best_dist = float("inf")

    for edge_id in sorted({int(x) for x in edge_ids}):
        poly = np.asarray(edge_polylines.get(int(edge_id), np.empty((0, 3))), dtype=np.float64)
        if poly.ndim != 2 or poly.shape[1] != 3 or len(poly) < 2:
            continue
        screen, valid = _project_xyz_to_screen(poly, viewproj, viewport_w, viewport_h)
        local_best = float("inf")
        for i in range(len(screen) - 1):
            if not (bool(valid[i]) and bool(valid[i + 1])):
                continue
            d = _point_to_segment_distance_sq(p, screen[i], screen[i + 1])
            if d < local_best:
                local_best = d
        if local_best < best_dist:
            best_dist = local_best
            best_edge = int(edge_id)

    if best_edge is None or best_dist > tol_sq:
        return None
    return int(best_edge)
