from __future__ import annotations

from collections import defaultdict, deque
from itertools import combinations
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np


Edge = Tuple[int, int]


def _norm_edge(edge: Sequence[int]) -> Edge:
    a = int(edge[0])
    b = int(edge[1])
    return (a, b) if a < b else (b, a)


def _edge_face_map(faces: np.ndarray) -> Dict[Edge, List[int]]:
    edge_to_faces: Dict[Edge, List[int]] = defaultdict(list)
    for fi, (a, b, c) in enumerate(np.asarray(faces, dtype=np.int64)):
        edge_to_faces[_norm_edge((a, b))].append(int(fi))
        edge_to_faces[_norm_edge((b, c))].append(int(fi))
        edge_to_faces[_norm_edge((c, a))].append(int(fi))
    return edge_to_faces


def _face_component_count(faces: np.ndarray, edge_to_faces: Dict[Edge, List[int]] | None = None) -> int:
    faces = np.asarray(faces, dtype=np.int64)
    if len(faces) == 0:
        return 0
    if edge_to_faces is None:
        edge_to_faces = _edge_face_map(faces)
    adj = [set() for _ in range(len(faces))]
    for linked in edge_to_faces.values():
        if len(linked) < 2:
            continue
        if len(linked) == 2:
            a, b = linked
            adj[a].add(b)
            adj[b].add(a)
            continue
        # Non-manifold: still treat as one connected fan for diagnostics.
        for a, b in combinations(linked, 2):
            adj[a].add(b)
            adj[b].add(a)

    seen: set[int] = set()
    comps = 0
    for start in range(len(faces)):
        if start in seen:
            continue
        comps += 1
        q = deque([start])
        seen.add(start)
        while q:
            cur = q.popleft()
            for nb in adj[cur]:
                if nb not in seen:
                    seen.add(nb)
                    q.append(nb)
    return comps


def _boundary_diagnostics(edge_to_faces: Dict[Edge, List[int]]) -> Tuple[int, int, int]:
    boundary_edges = [e for e, fs in edge_to_faces.items() if len(fs) == 1]
    if not boundary_edges:
        return 0, 0, 0

    vadj: Dict[int, set[int]] = defaultdict(set)
    for a, b in boundary_edges:
        vadj[a].add(b)
        vadj[b].add(a)

    seen_v: set[int] = set()
    loop_count = 0
    branch_vertices = 0
    open_chain_components = 0
    for v in vadj:
        if v in seen_v:
            continue
        stack = [v]
        comp_vertices: List[int] = []
        seen_v.add(v)
        while stack:
            cur = stack.pop()
            comp_vertices.append(cur)
            for nb in vadj[cur]:
                if nb not in seen_v:
                    seen_v.add(nb)
                    stack.append(nb)
        degs = [len(vadj[x]) for x in comp_vertices]
        branch_vertices += sum(1 for d in degs if d > 2)
        if all(d == 2 for d in degs):
            loop_count += 1
        else:
            open_chain_components += 1
    return loop_count, branch_vertices, open_chain_components


def topology_report(faces: np.ndarray) -> Dict[str, int]:
    faces = np.asarray(faces, dtype=np.int64)
    if faces.ndim != 2 or (len(faces) and faces.shape[1] != 3):
        raise ValueError("Faces must be Nx3.")
    if len(faces) == 0:
        return {
            "open_edges": 0,
            "non_manifold_edges": 0,
            "connected_components": 0,
            "boundary_loops": 0,
            "boundary_branch_vertices": 0,
            "boundary_open_components": 0,
        }

    edge_to_faces = _edge_face_map(faces)
    open_edges = 0
    non_manifold = 0
    for fs in edge_to_faces.values():
        if len(fs) == 1:
            open_edges += 1
        elif len(fs) > 2:
            non_manifold += 1
    boundary_loops, branch_vertices, open_boundary_comps = _boundary_diagnostics(edge_to_faces)
    return {
        "open_edges": int(open_edges),
        "non_manifold_edges": int(non_manifold),
        "connected_components": int(_face_component_count(faces, edge_to_faces=edge_to_faces)),
        "boundary_loops": int(boundary_loops),
        "boundary_branch_vertices": int(branch_vertices),
        "boundary_open_components": int(open_boundary_comps),
    }


def extract_mesh_candidate_edges(
    faces: np.ndarray,
    *,
    face_indices: np.ndarray | None = None,
    boundary_only: bool = False,
) -> List[Edge]:
    tri = np.asarray(faces, dtype=np.int64)
    if tri.ndim != 2 or (len(tri) and tri.shape[1] != 3):
        raise ValueError("faces must be Nx3.")
    if len(tri) == 0:
        return []
    if face_indices is not None:
        idx = np.asarray(face_indices, dtype=np.int64)
        idx = idx[(idx >= 0) & (idx < len(tri))]
        if len(idx) == 0:
            return []
        tri = tri[idx]

    edge_count: Dict[Edge, int] = defaultdict(int)
    for a, b, c in tri:
        edge_count[_norm_edge((a, b))] += 1
        edge_count[_norm_edge((b, c))] += 1
        edge_count[_norm_edge((c, a))] += 1
    if boundary_only:
        return sorted([e for e, c in edge_count.items() if c == 1])
    return sorted(edge_count.keys())


def _point_segment_distance_sq_3d(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom <= 1e-18:
        d = point - a
        return float(np.dot(d, d))
    t = float(np.dot(point - a, ab) / denom)
    t = max(0.0, min(1.0, t))
    q = a + t * ab
    d = point - q
    return float(np.dot(d, d))


def _largest_connected_edge_subset(edges: Sequence[Edge]) -> List[Edge]:
    normed = sorted({_norm_edge(e) for e in edges})
    if not normed:
        return []
    vertex_to_edges: Dict[int, List[Edge]] = defaultdict(list)
    for e in normed:
        vertex_to_edges[e[0]].append(e)
        vertex_to_edges[e[1]].append(e)

    unseen = set(normed)
    best_comp: List[Edge] = []
    while unseen:
        start = min(unseen)
        stack = [start]
        unseen.remove(start)
        comp: List[Edge] = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for v in cur:
                for nb in vertex_to_edges[v]:
                    if nb in unseen:
                        unseen.remove(nb)
                        stack.append(nb)
        comp_sorted = sorted(comp)
        if len(comp_sorted) > len(best_comp):
            best_comp = comp_sorted
    return best_comp


def map_brep_edge_polylines_to_mesh_edges(
    vertices: np.ndarray,
    faces: np.ndarray,
    edge_polylines: Dict[int, np.ndarray],
    *,
    edge_ids: Iterable[int] | None = None,
    patch_face_indices: np.ndarray | None = None,
    boundary_only: bool = True,
    tolerance: float | None = None,
) -> Dict[int, List[Edge]]:
    verts = np.asarray(vertices, dtype=np.float64)
    tri = np.asarray(faces, dtype=np.int64)
    if verts.ndim != 2 or verts.shape[1] != 3:
        raise ValueError("vertices must be Nx3.")
    if tri.ndim != 2 or (len(tri) and tri.shape[1] != 3):
        raise ValueError("faces must be Nx3.")

    requested = sorted({int(eid) for eid in (edge_ids if edge_ids is not None else edge_polylines.keys())})
    out: Dict[int, List[Edge]] = {int(eid): [] for eid in requested}
    if len(verts) == 0 or len(tri) == 0 or not requested:
        return out

    candidate_edges = extract_mesh_candidate_edges(
        tri,
        face_indices=patch_face_indices,
        boundary_only=bool(boundary_only),
    )
    if not candidate_edges:
        if boundary_only:
            candidate_edges = extract_mesh_candidate_edges(tri, face_indices=patch_face_indices, boundary_only=False)
    if not candidate_edges:
        return out

    edge_arr = np.asarray(candidate_edges, dtype=np.int64)
    va = verts[edge_arr[:, 0]]
    vb = verts[edge_arr[:, 1]]
    edge_mid = 0.5 * (va + vb)
    edge_vec = vb - va
    edge_len = np.linalg.norm(edge_vec, axis=1)
    safe_len = np.where(edge_len < 1e-12, 1.0, edge_len)
    edge_dir = edge_vec / safe_len[:, None]

    if tolerance is None:
        median_len = float(np.median(edge_len[edge_len > 1e-12])) if np.any(edge_len > 1e-12) else 0.0
        tolerance = max(median_len * 1.75, 1e-3)
    tol = float(max(tolerance, 1e-6))
    search_radius = tol * 1.5

    kd_tree = None
    try:
        from scipy.spatial import cKDTree  # type: ignore

        kd_tree = cKDTree(edge_mid)
    except Exception:
        kd_tree = None

    for edge_id in requested:
        poly = np.asarray(edge_polylines.get(int(edge_id), np.empty((0, 3))), dtype=np.float64)
        if poly.ndim != 2 or poly.shape[1] != 3 or len(poly) < 2:
            out[int(edge_id)] = []
            continue

        mapped: List[Edge] = []
        for i in range(len(poly) - 1):
            p0 = np.asarray(poly[i], dtype=np.float64)
            p1 = np.asarray(poly[i + 1], dtype=np.float64)
            seg_vec = p1 - p0
            seg_len = float(np.linalg.norm(seg_vec))
            if seg_len <= 1e-12:
                continue
            seg_mid = 0.5 * (p0 + p1)
            seg_dir = seg_vec / seg_len

            if kd_tree is not None:
                cand_idx = kd_tree.query_ball_point(seg_mid, search_radius)
            else:
                d2 = np.sum((edge_mid - seg_mid[None, :]) ** 2, axis=1)
                cand_idx = np.nonzero(d2 <= (search_radius * search_radius))[0].tolist()
            if not cand_idx:
                # Fallback nearest midpoint when radius misses due sampling mismatch.
                d2 = np.sum((edge_mid - seg_mid[None, :]) ** 2, axis=1)
                cand_idx = [int(np.argmin(d2))]

            best_edge = None
            best_score = float("inf")
            for idx in cand_idx:
                idx_i = int(idx)
                dist_sq = _point_segment_distance_sq_3d(seg_mid, va[idx_i], vb[idx_i])
                orient = float(abs(np.clip(np.dot(seg_dir, edge_dir[idx_i]), -1.0, 1.0)))
                # Distance dominates; orientation resolves ambiguous neighbors.
                score = (dist_sq / (tol * tol)) + (1.0 - orient) * 0.35
                if score < best_score:
                    best_score = score
                    best_edge = candidate_edges[idx_i]
            if best_edge is not None:
                mapped.append(_norm_edge(best_edge))

        # Keep a contiguous subset to avoid scattered edge picks from noisy sampling.
        mapped_unique = sorted(set(mapped))
        mapped_connected = _largest_connected_edge_subset(mapped_unique)
        out[int(edge_id)] = mapped_connected if mapped_connected else mapped_unique
    return out


def _try_libigl_cut_mesh(vertices: np.ndarray, faces: np.ndarray, cut_edges: set[Edge]):
    """Optional seam-cut path. Falls back to vertex-duplication unless a known helper is available."""
    try:
        import igl  # type: ignore
    except Exception:
        return None
    # No stable libigl Python seam-cut API is guaranteed across builds here.
    # Keep a conservative fallback unless a known helper is exposed.
    if not hasattr(igl, "cut_mesh"):
        return None
    return None


def cut_mesh_along_edges(
    vertices: np.ndarray,
    faces: np.ndarray,
    cut_edges: Iterable[Sequence[int]],
    *,
    prefer_libigl: bool = True,
) -> Dict[str, object]:
    """Cut a triangle mesh along undirected edge set via vertex fan splitting.

    Returns vertices/faces of the cut mesh plus parent-vertex mapping and topology diagnostics.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("Faces must be triangular Nx3 array.")

    requested_cut_edges: set[Edge] = {_norm_edge(e) for e in cut_edges}
    if not requested_cut_edges:
        topo = topology_report(faces)
        return {
            "vertices": vertices,
            "faces": faces,
            "vertex_parent": np.arange(len(vertices), dtype=np.int64),
            "used_cut_edges": [],
            "missing_cut_edges": [],
            "topology_before": topo,
            "topology_after": topo.copy(),
            "used_libigl": False,
        }

    if prefer_libigl:
        libigl_res = _try_libigl_cut_mesh(vertices, faces, requested_cut_edges)
        if libigl_res is not None:
            return libigl_res

    edge_to_faces = _edge_face_map(faces)
    present_edges = set(edge_to_faces.keys())
    used_cut_edges = sorted(e for e in requested_cut_edges if e in present_edges)
    missing_cut_edges = sorted(e for e in requested_cut_edges if e not in present_edges)

    topo_before = topology_report(faces)
    if not used_cut_edges:
        return {
            "vertices": vertices,
            "faces": faces,
            "vertex_parent": np.arange(len(vertices), dtype=np.int64),
            "used_cut_edges": [],
            "missing_cut_edges": missing_cut_edges,
            "topology_before": topo_before,
            "topology_after": topo_before.copy(),
            "used_libigl": False,
        }

    cut_edge_set = set(used_cut_edges)

    n_vertices = len(vertices)
    incident_faces: List[List[int]] = [[] for _ in range(n_vertices)]
    for fi, tri in enumerate(faces):
        for v in tri:
            incident_faces[int(v)].append(int(fi))

    # Per-vertex adjacency of incident faces through NON-cut edges that touch that vertex.
    vf_links: List[Dict[int, set[int]]] = [defaultdict(set) for _ in range(n_vertices)]
    for edge, linked_faces in edge_to_faces.items():
        if edge in cut_edge_set or len(linked_faces) < 2:
            continue
        for f0, f1 in combinations(linked_faces, 2):
            for v in edge:
                vf_links[int(v)][int(f0)].add(int(f1))
                vf_links[int(v)][int(f1)].add(int(f0))

    new_vertices: List[np.ndarray] = [vertices[i].copy() for i in range(n_vertices)]
    vertex_parent: List[int] = list(range(n_vertices))
    vertex_face_to_new: Dict[Tuple[int, int], int] = {}

    for v in range(n_vertices):
        faces_here = sorted(set(int(fi) for fi in incident_faces[v]))
        if not faces_here:
            continue
        if len(faces_here) == 1:
            vertex_face_to_new[(faces_here[0], v)] = v
            continue

        local_links = vf_links[v]
        seen_faces: set[int] = set()
        components: List[List[int]] = []
        for start in faces_here:
            if start in seen_faces:
                continue
            q = deque([start])
            seen_faces.add(start)
            comp: List[int] = []
            while q:
                cur = q.popleft()
                comp.append(cur)
                for nb in sorted(local_links.get(cur, ())):
                    if nb not in seen_faces:
                        seen_faces.add(nb)
                        q.append(nb)
            components.append(sorted(comp))

        components.sort(key=lambda comp: (comp[0], len(comp)))
        for comp_idx, comp in enumerate(components):
            if comp_idx == 0:
                new_vid = v
            else:
                new_vid = len(new_vertices)
                new_vertices.append(vertices[v].copy())
                vertex_parent.append(v)
            for fi in comp:
                vertex_face_to_new[(fi, v)] = new_vid

    cut_faces = np.empty_like(faces, dtype=np.int64)
    for fi, tri in enumerate(faces):
        for k, v in enumerate(tri):
            key = (int(fi), int(v))
            cut_faces[fi, k] = int(vertex_face_to_new.get(key, int(v)))

    cut_vertices = np.asarray(new_vertices, dtype=np.float64)
    vertex_parent_arr = np.asarray(vertex_parent, dtype=np.int64)
    topo_after = topology_report(cut_faces)

    return {
        "vertices": cut_vertices,
        "faces": cut_faces,
        "vertex_parent": vertex_parent_arr,
        "used_cut_edges": used_cut_edges,
        "missing_cut_edges": missing_cut_edges,
        "topology_before": topo_before,
        "topology_after": topo_after,
        "used_libigl": False,
    }


def original_edge_instances(
    faces: np.ndarray,
    vertex_parent: np.ndarray,
    original_edge: Sequence[int],
) -> List[Edge]:
    faces = np.asarray(faces, dtype=np.int64)
    vertex_parent = np.asarray(vertex_parent, dtype=np.int64)
    target = _norm_edge(original_edge)
    found: set[Edge] = set()
    for a, b, c in faces:
        for u, v in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
            if _norm_edge((vertex_parent[u], vertex_parent[v])) == target and u != v:
                found.add(_norm_edge((u, v)))
    return sorted(found)


def choose_anchor_edge_instance(
    faces: np.ndarray,
    vertex_parent: np.ndarray,
    original_edge: Sequence[int],
) -> Edge | None:
    instances = original_edge_instances(faces, vertex_parent, original_edge)
    if not instances:
        return None
    edge_to_faces = _edge_face_map(np.asarray(faces, dtype=np.int64))
    boundary_instances = [e for e in instances if len(edge_to_faces.get(e, ())) == 1]
    if boundary_instances:
        return min(boundary_instances)
    return min(instances)
