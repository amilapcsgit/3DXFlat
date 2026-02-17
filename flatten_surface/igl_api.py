import igl
import numpy as np

from .geometry import plane_through_3_points, rotate_points, rotation_matrix_from_vectors, plane_normal_vector


def init_unfold(vertices, faces, id_vertex):
    init_points_ids = np.array(faces[id_vertex], dtype=np.int64)
    x1 = vertices[init_points_ids[0]][0]
    y1 = vertices[init_points_ids[0]][1]
    z1 = vertices[init_points_ids[0]][2]
    x2 = vertices[init_points_ids[1]][0]
    y2 = vertices[init_points_ids[1]][1]
    z2 = vertices[init_points_ids[1]][2]
    x3 = vertices[init_points_ids[2]][0]
    y3 = vertices[init_points_ids[2]][1]
    z3 = vertices[init_points_ids[2]][2]
    points = np.array([
        [x1, y1, z1],
        [x2, y2, z2],
        [x3, y3, z3]
    ])
    plan = plane_through_3_points(x1, y1, z1, x2, y2, z2, x3, y3, z3)
    points = rotate_points(points, rotation_matrix_from_vectors(plane_normal_vector(plan), np.array([0, 0, 1])))
    points -= points[0]
    x, y, _ = points.T
    init_points_pos = np.ascontiguousarray(np.asarray([x, y], dtype=np.double).T)
    return init_points_ids, init_points_pos, plan


def unfold(vertices, faces, init_points_ids, init_points_pos, method="LSCM"):
    v = np.ascontiguousarray(vertices, dtype=np.float64)
    f = np.ascontiguousarray(faces, dtype=np.int64)
    b = np.ascontiguousarray(init_points_ids, dtype=np.int64)
    bc = np.ascontiguousarray(init_points_pos, dtype=np.float64)

    if method == "LSCM":
        res = igl.lscm(v, f, b, bc)
        if isinstance(res, tuple):
            unwrap = res[0]
        else:
            unwrap = res
    elif method == "ARAP":
        # ARAP needs an initial guess. Use LSCM.
        res_lscm = igl.lscm(v, f, b, bc)
        unwrap_init = res_lscm[0] if isinstance(res_lscm, tuple) else res_lscm

        # Precompute ARAP
        # igl.arap_precomputation(V, F, dim, b)
        # We use dim=2 for parameterization
        arap_data = igl.ARAPData()
        # Keep solve time practical for large production meshes.
        if f.shape[0] > 50000:
            arap_data.max_iter = 12
        elif f.shape[0] > 20000:
            arap_data.max_iter = 20
        else:
            arap_data.max_iter = 30
        # ARAPEnergyType: 0: Spokes, 1: Spokes-and-rims, 2: Elements (default)
        igl.arap_precomputation(v, f, 2, b, arap_data)

        # Solve
        unwrap = igl.arap_solve(bc, arap_data, unwrap_init)
    else:
        raise ValueError(f"Unknown method: {method}")

    if unwrap is None or not len(unwrap):
        raise Exception("Impossible to unfold")
    return unwrap


def get_all_bounds(faces):
    res = igl.boundary_facets(faces)
    boundary_facets = res[0] if isinstance(res, tuple) else res
    if boundary_facets is None or len(boundary_facets) == 0:
        return []

    adjacency = {}
    edges = set()
    for edge in boundary_facets:
        u, v = int(edge[0]), int(edge[1])
        if u == v:
            continue
        adjacency.setdefault(u, []).append(v)
        adjacency.setdefault(v, []).append(u)
        edges.add(tuple(sorted((u, v))))

    loops = []
    visited_edges = set()

    for edge in list(edges):
        if edge in visited_edges:
            continue

        start, current = edge
        loop = [start, current]
        visited_edges.add(edge)
        prev = start

        # Keep traversal bounded by number of boundary edges.
        for _ in range(len(edges) + 1):
            neighbors = adjacency.get(current, [])
            next_vertex = None
            for candidate in neighbors:
                if candidate == prev:
                    continue
                cand_edge = tuple(sorted((current, candidate)))
                if cand_edge not in visited_edges:
                    next_vertex = candidate
                    break

            if next_vertex is None:
                # Open chain end.
                break

            cand_edge = tuple(sorted((current, next_vertex)))
            visited_edges.add(cand_edge)

            if next_vertex == start:
                break

            loop.append(next_vertex)
            prev, current = current, next_vertex

        if len(loop) >= 3:
            loops.append(loop)

    return loops
