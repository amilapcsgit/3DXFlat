from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh


def load_mesh_file(path: str):
    ext = Path(path).suffix.lower()
    if ext in {".stp", ".step"}:
        return _load_step(path)
    return trimesh.load(path)


def _has_faces(mesh) -> bool:
    try:
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        return len(faces) > 0
    except Exception:
        return False


def _load_step(path: str):
    # First try trimesh directly in case environment already has STEP readers configured.
    try:
        mesh = trimesh.load(path)
        if _has_faces(mesh):
            return mesh
    except Exception:
        pass

    try:
        import gmsh
    except Exception as exc:
        raise RuntimeError(
            "STEP import requires optional dependency `gmsh`. Install with: pip install gmsh"
        ) from exc

    initialized_here = False
    try:
        if not gmsh.isInitialized():
            # STEP loading runs in a worker thread in the Qt app. Avoid Python signal registration
            # from non-main threads by disabling gmsh interrupt handlers.
            try:
                gmsh.initialize(interruptible=False)
            except TypeError:
                try:
                    gmsh.initialize([], True, False, False)
                except TypeError:
                    gmsh.initialize()
            initialized_here = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.clear()
        gmsh.open(path)
        try:
            gmsh.model.occ.synchronize()
        except Exception:
            pass
        gmsh.model.mesh.generate(2)

        node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
        if len(node_tags) == 0:
            raise RuntimeError("No mesh nodes were generated from STEP geometry.")
        vertices = np.asarray(node_coords, dtype=np.float64).reshape(-1, 3)
        tag_to_index = {int(tag): i for i, tag in enumerate(np.asarray(node_tags, dtype=np.int64).tolist())}

        element_types, _, element_nodes = gmsh.model.mesh.getElements(2)
        faces: list[list[int]] = []
        for e_type, e_nodes in zip(element_types, element_nodes):
            _, _, _, num_nodes, _, _ = gmsh.model.mesh.getElementProperties(int(e_type))
            num_nodes = int(num_nodes)
            raw = np.asarray(e_nodes, dtype=np.int64)
            if raw.size == 0 or num_nodes < 3:
                continue
            elems = raw.reshape(-1, num_nodes)
            if num_nodes == 3:
                for tri in elems:
                    faces.append([tag_to_index[int(tri[0])], tag_to_index[int(tri[1])], tag_to_index[int(tri[2])]])
                continue
            if num_nodes == 4:
                for quad in elems:
                    a, b, c, d = [tag_to_index[int(v)] for v in quad[:4]]
                    faces.append([a, b, c])
                    faces.append([a, c, d])
                continue
            for poly in elems:
                idx = [tag_to_index[int(v)] for v in poly if int(v) in tag_to_index]
                if len(idx) < 3:
                    continue
                root = idx[0]
                for i in range(1, len(idx) - 1):
                    faces.append([root, idx[i], idx[i + 1]])

        if not faces:
            raise RuntimeError("No surface triangles were extracted from STEP file.")
        tri_faces = np.asarray(faces, dtype=np.int64)
        canonical = np.sort(tri_faces, axis=1)
        _, unique_idx = np.unique(canonical, axis=0, return_index=True)
        tri_faces = tri_faces[np.sort(unique_idx)]
        return trimesh.Trimesh(vertices=vertices, faces=tri_faces, process=False)
    finally:
        if initialized_here:
            gmsh.finalize()
