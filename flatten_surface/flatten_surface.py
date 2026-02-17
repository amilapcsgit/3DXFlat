import os
import tkinter as tk
from tkinter import filedialog
import heapq

import numpy as np

from .display import plot
from .igl_api import init_unfold, unfold, get_all_bounds
from .import_export import load, export_svg, export_dxf, get_unit_scale
from .score import compute_deformation


def _polygon_length_2d(points_2d):
    if len(points_2d) < 2:
        return 0.0
    deltas = np.diff(points_2d, axis=0)
    return float(np.sum(np.linalg.norm(deltas, axis=1)))


def _polygon_length_3d(points_3d):
    if len(points_3d) < 2:
        return 0.0
    deltas = np.diff(points_3d, axis=0)
    return float(np.sum(np.linalg.norm(deltas, axis=1)))


def _compute_metrics(vertices, faces, unwrap, bounds, scale):
    tri3d = vertices[faces] * scale
    tri2d = unwrap[faces] * scale

    # Triangle area = 0.5 * |cross(e1, e2)|
    area3d = 0.5 * np.sum(np.linalg.norm(np.cross(tri3d[:, 1] - tri3d[:, 0], tri3d[:, 2] - tri3d[:, 0]), axis=1))
    cross2d = (
        (tri2d[:, 1, 0] - tri2d[:, 0, 0]) * (tri2d[:, 2, 1] - tri2d[:, 0, 1])
        - (tri2d[:, 1, 1] - tri2d[:, 0, 1]) * (tri2d[:, 2, 0] - tri2d[:, 0, 0])
    )
    area2d = 0.5 * float(np.sum(np.abs(cross2d)))

    perimeter_3d = 0.0
    perimeter_2d = 0.0
    for bound in bounds:
        if len(bound) < 2:
            continue
        idx = np.asarray(bound, dtype=np.int64)
        loop3d = vertices[idx] * scale
        loop2d = unwrap[idx] * scale

        loop3d_closed = np.vstack([loop3d, loop3d[:1]])
        loop2d_closed = np.vstack([loop2d, loop2d[:1]])

        perimeter_3d += _polygon_length_3d(loop3d_closed)
        perimeter_2d += _polygon_length_2d(loop2d_closed)

    area_error_pct = abs(area2d - area3d) / max(area3d, 1e-12) * 100.0
    perimeter_error_pct = abs(perimeter_2d - perimeter_3d) / max(perimeter_3d, 1e-12) * 100.0

    return {
        "area_3d_mm2": float(area3d),
        "area_2d_mm2": float(area2d),
        "area_error_pct": float(area_error_pct),
        "perimeter_3d_mm": float(perimeter_3d),
        "perimeter_2d_mm": float(perimeter_2d),
        "perimeter_error_pct": float(perimeter_error_pct),
    }


def _loop_area_2d(points_2d):
    if len(points_2d) < 3:
        return 0.0
    x = points_2d[:, 0]
    y = points_2d[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - y * np.roll(x, -1)))


def _select_bounds_for_export(bounds, unwrap, mode="outer_only", hole_area_ratio=0.02):
    if not bounds:
        return bounds

    if mode == "all_loops":
        return bounds

    loop_areas = []
    for i, bound in enumerate(bounds):
        pts = unwrap[np.asarray(bound, dtype=np.int64)]
        loop_areas.append((i, abs(_loop_area_2d(pts))))

    if not loop_areas:
        return bounds

    outer_idx, outer_area = max(loop_areas, key=lambda it: it[1])
    if mode == "outer_only":
        return [bounds[outer_idx]]

    # Keep outer + only significant holes.
    selected = [bounds[outer_idx]]
    min_hole_area = max(outer_area * hole_area_ratio, 1e-12)
    for i, area in loop_areas:
        if i == outer_idx:
            continue
        if area >= min_hole_area:
            selected.append(bounds[i])
    return selected


def _build_vertex_adjacency(vertices, faces):
    n = len(vertices)
    adjacency = [[] for _ in range(n)]
    edges = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    for u, v in edges:
        u = int(u)
        v = int(v)
        if u == v:
            continue
        w = float(np.linalg.norm(vertices[u] - vertices[v]))
        adjacency[u].append((v, w))
        adjacency[v].append((u, w))
    return adjacency


def _shortest_path(adjacency, start, goals):
    goals = set(int(g) for g in goals)
    dist = {int(start): 0.0}
    prev = {}
    pq = [(0.0, int(start))]
    visited = set()
    goal_hit = None
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u in goals:
            goal_hit = u
            break
        for v, w in adjacency[u]:
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if goal_hit is None:
        return None
    path = [goal_hit]
    while path[-1] != int(start):
        path.append(prev[path[-1]])
    path.reverse()
    return path


def _suggest_relief_cut(vertices, faces, bounds, strain_percent, threshold_pct=3.0):
    if len(bounds) == 0:
        return None
    boundary_vertices = np.unique(np.concatenate([np.asarray(b, dtype=np.int64) for b in bounds]))
    if len(boundary_vertices) == 0:
        return None

    high_faces = np.where(np.asarray(strain_percent, dtype=np.float64) >= threshold_pct)[0]
    if len(high_faces) == 0:
        return None
    boundary_set = set(int(v) for v in boundary_vertices.tolist())
    high_face_order = high_faces[np.argsort(np.asarray(strain_percent)[high_faces])[::-1]]
    seed_vertex = None
    for face_id in high_face_order:
        tri = [int(v) for v in faces[int(face_id)]]
        interior = [v for v in tri if v not in boundary_set]
        if interior:
            seed_vertex = interior[0]
            break
    if seed_vertex is None:
        # Fallback to farthest high-strain face centroid vertex from boundary.
        seed_face = int(high_face_order[0])
        tri = [int(v) for v in faces[seed_face]]
        seed_vertex = tri[0]
    if seed_vertex in boundary_set:
        # No interior route available.
        return None

    adjacency = _build_vertex_adjacency(vertices, faces)
    path = _shortest_path(adjacency, seed_vertex, boundary_vertices)
    if path is None or len(path) < 2:
        return None
    return np.asarray(path, dtype=np.int64)


def flatten_mesh(
    vertices,
    faces,
    path_output,
    path_png=None,
    vertice_init_id=0,
    show_plot=True,
    input_unit="mm",
    method="LSCM",
    boundary_mode="outer_only",
    seam_allowance_mm=0.0,
    align_to_x=False,
    label_text=None,
    auto_relief_cut=False,
    relief_threshold_pct=3.0,
):
    bounds = get_all_bounds(faces)
    if not bounds:
        raise ValueError(
            "Could not find open boundary loops to export. "
            "The selected mesh is likely a closed solid. "
            "Try selecting a single surface patch."
        )

    init_points_ids, init_points_pos, plan = init_unfold(vertices, faces, vertice_init_id)
    unwrap = unfold(vertices, faces, init_points_ids, init_points_pos, method=method)
    export_bounds = _select_bounds_for_export(bounds, unwrap, mode=boundary_mode)
    strain_percent = compute_deformation(vertices, faces, unwrap, verbose=True)
    relief_path_vertex_ids = None
    relief_path_2d = None
    if auto_relief_cut:
        relief_path_vertex_ids = _suggest_relief_cut(
            vertices=vertices,
            faces=faces,
            bounds=export_bounds,
            strain_percent=strain_percent,
            threshold_pct=relief_threshold_pct,
        )
        if relief_path_vertex_ids is not None:
            relief_path_2d = unwrap[relief_path_vertex_ids]

    if show_plot:
        plot(vertices, faces, unwrap, init_points_pos, plan, init_points_ids, export_bounds, strain_percent, path_png)

    scale = get_unit_scale(input_unit)
    if path_output.lower().endswith(".dxf"):
        export_dxf(
            unwrap,
            export_bounds,
            path_output,
            scale=scale,
            seam_allowance_mm=seam_allowance_mm,
            align_to_x=align_to_x,
            label_text=label_text,
            relief_cut_path=relief_path_2d,
        )
    else:
        export_svg(unwrap, export_bounds, path_output, scale=scale)

    metrics = _compute_metrics(vertices, faces, unwrap, export_bounds, scale)
    return {
        "bounds_found": len(bounds),
        "bounds_exported": len(export_bounds),
        "metrics": metrics,
        "method": method,
        "boundary_mode": boundary_mode,
        "seam_allowance_mm": float(seam_allowance_mm),
        "strain_percent_per_face": strain_percent,
        "unwrap": unwrap,
        "export_bounds": export_bounds,
        "relief_path_vertex_ids": relief_path_vertex_ids,
        "relief_path_2d": relief_path_2d,
    }


def solve_flatten(
    vertices,
    faces,
    input_unit="mm",
    method="LSCM",
    boundary_mode="outer_only",
    relief_threshold_pct=3.0,
):
    bounds = get_all_bounds(faces)
    if not bounds:
        raise ValueError(
            "Could not find open boundary loops to export. "
            "The selected mesh is likely a closed solid. "
            "Try selecting a single surface patch."
        )

    init_points_ids, init_points_pos, plan = init_unfold(vertices, faces, 0)
    unwrap = unfold(vertices, faces, init_points_ids, init_points_pos, method=method)
    export_bounds = _select_bounds_for_export(bounds, unwrap, mode=boundary_mode)
    strain_percent = compute_deformation(vertices, faces, unwrap, verbose=False)
    relief_path_vertex_ids = _suggest_relief_cut(
        vertices=vertices,
        faces=faces,
        bounds=export_bounds,
        strain_percent=strain_percent,
        threshold_pct=relief_threshold_pct,
    )
    relief_path_2d = unwrap[relief_path_vertex_ids] if relief_path_vertex_ids is not None else None
    scale = get_unit_scale(input_unit)
    metrics = _compute_metrics(vertices, faces, unwrap, export_bounds, scale)
    return {
        "bounds_found": len(bounds),
        "bounds_exported": len(export_bounds),
        "method": method,
        "boundary_mode": boundary_mode,
        "metrics": metrics,
        "strain_percent_per_face": strain_percent,
        "unwrap": unwrap,
        "export_bounds": export_bounds,
        "relief_path_vertex_ids": relief_path_vertex_ids,
        "relief_path_2d": relief_path_2d,
    }


def main(
    path_input=None,
    path_output=None,
    path_png=None,
    vertice_init_id=0,
    show_plot=True,
    input_unit="mm",
    method="LSCM",
    boundary_mode="outer_only",
    seam_allowance_mm=0.0,
    align_to_x=False,
    label_text=None,
    auto_relief_cut=False,
    relief_threshold_pct=3.0,
):
    if path_input is None or not os.path.isfile(path_input):
        root = tk.Tk()
        root.withdraw()
        path_input = filedialog.askopenfilename(
            initialdir=os.path.join(os.path.dirname(__file__), "..", "data"),
            title="Please select a 3D surface file to unfold",
            filetypes=(("3D files", "*.stl *.STL *.obj *.3ds"), ("All files", "*.*")),
        )
        if not path_input:
            return None

    if path_png is None:
        stem = ".".join(os.path.basename(path_input).split(".")[:-1])
        path_png = os.path.join(os.path.dirname(path_input), f"{stem}.png")

    if path_output is None:
        stem = ".".join(os.path.basename(path_input).split(".")[:-1])
        path_output = os.path.join(os.path.dirname(path_input), f"{stem}.svg")

    vertices, faces = load(path_input, prefer_open_surface=True)
    return flatten_mesh(
        vertices=vertices,
        faces=faces,
        path_output=path_output,
        path_png=path_png,
        vertice_init_id=vertice_init_id,
        show_plot=show_plot,
        input_unit=input_unit,
        method=method,
        boundary_mode=boundary_mode,
        seam_allowance_mm=seam_allowance_mm,
        align_to_x=align_to_x,
        label_text=label_text,
        auto_relief_cut=auto_relief_cut,
        relief_threshold_pct=relief_threshold_pct,
    )
