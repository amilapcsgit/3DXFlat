from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np


@dataclass
class BrepModel:
    source_path: str
    shape: object
    faces: List[object]
    edges: List[object]
    tri_mesh_vertices: np.ndarray
    tri_mesh_faces: np.ndarray
    tri_face_id: np.ndarray
    edge_polylines: Dict[int, np.ndarray]
    face_boundary_edge_ids: Dict[int, List[int]]
    bbox: Tuple[float, float, float, float, float, float]
    units_label: str


def is_brep_extension(path: str) -> bool:
    ext = Path(str(path)).suffix.lower()
    return ext in {".step", ".stp", ".iges", ".igs"}


def is_occ_available() -> Tuple[bool, str | None]:
    try:
        import OCC.Core  # type: ignore  # noqa: F401
    except Exception as exc:
        return False, str(exc)
    return True, None


def load_brep(path: str, *, deflection: float = 0.6, angle_rad: float = 0.35) -> BrepModel:
    ok, reason = is_occ_available()
    if not ok:
        raise RuntimeError(
            "B-Rep import requires optional dependency `pythonocc-core`."
            + (f" Import error: {reason}" if reason else "")
        )

    ext = Path(str(path)).suffix.lower()
    if ext not in {".step", ".stp", ".iges", ".igs"}:
        raise ValueError(f"Unsupported B-Rep extension: {ext}")

    shape = _read_shape(path, ext)
    shape = _as_compound(shape)
    faces, edges, face_map, edge_map = _collect_topology(shape)

    _mesh_shape(shape, deflection=deflection, angle_rad=angle_rad)
    (
        tri_vertices,
        tri_faces,
        tri_face_id,
        bbox,
    ) = _extract_face_triangulation(faces, face_map, deflection=deflection)
    edge_polylines = _extract_edge_polylines(edges, deflection=max(deflection * 0.5, 0.05))
    face_boundary_edge_ids = _extract_face_boundary_edge_ids(faces, edge_map)
    units_label = _detect_units_label(ext)

    return BrepModel(
        source_path=str(path),
        shape=shape,
        faces=faces,
        edges=edges,
        tri_mesh_vertices=tri_vertices,
        tri_mesh_faces=tri_faces,
        tri_face_id=tri_face_id,
        edge_polylines=edge_polylines,
        face_boundary_edge_ids=face_boundary_edge_ids,
        bbox=bbox,
        units_label=units_label,
    )


def _read_shape(path: str, ext: str):
    from OCC.Core.IFSelect import IFSelect_RetDone  # type: ignore
    from OCC.Core.IGESControl import IGESControl_Reader  # type: ignore
    from OCC.Core.STEPControl import STEPControl_Reader  # type: ignore

    if ext in {".step", ".stp"}:
        reader = STEPControl_Reader()
    elif ext in {".iges", ".igs"}:
        reader = IGESControl_Reader()
    else:
        raise ValueError(f"Unsupported B-Rep extension: {ext}")

    status = int(reader.ReadFile(str(path)))
    if status != int(IFSelect_RetDone):
        raise RuntimeError(f"OpenCascade could not read B-Rep file: {Path(path).name}")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape is None or bool(shape.IsNull()):
        raise RuntimeError("B-Rep file loaded but shape is empty.")
    return shape


def _as_compound(shape):
    from OCC.Core.BRep import BRep_Builder  # type: ignore
    from OCC.Core.TopoDS import TopoDS_Compound  # type: ignore

    comp = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(comp)
    builder.Add(comp, shape)
    return comp


def _collect_topology(shape):
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_FACE  # type: ignore
    from OCC.Core.TopExp import TopExp, TopExp_Explorer  # type: ignore
    from OCC.Core.TopTools import TopTools_IndexedMapOfShape  # type: ignore
    from OCC.Core.TopoDS import topods  # type: ignore

    face_map = TopTools_IndexedMapOfShape()
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes(shape, TopAbs_FACE, face_map)
    TopExp.MapShapes(shape, TopAbs_EDGE, edge_map)

    faces: List[object] = []
    edges: List[object] = []

    exp_face = TopExp_Explorer(shape, TopAbs_FACE)
    while exp_face.More():
        faces.append(topods.Face(exp_face.Current()))
        exp_face.Next()

    exp_edge = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp_edge.More():
        edges.append(topods.Edge(exp_edge.Current()))
        exp_edge.Next()

    if not faces:
        raise RuntimeError("B-Rep file has no faces.")
    if not edges:
        raise RuntimeError("B-Rep file has no edges.")
    return faces, edges, face_map, edge_map


def _mesh_shape(shape, *, deflection: float, angle_rad: float) -> None:
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh  # type: ignore

    lin = float(max(deflection, 1e-4))
    ang = float(max(angle_rad, 1e-5))
    mesher = BRepMesh_IncrementalMesh(shape, lin, False, ang, True)
    try:
        mesher.Perform()
    except Exception:
        # Some pythonocc builds mesh during construction.
        pass


def _tri_nodes_and_indices(triangulation) -> Tuple[Sequence[object], List[Tuple[int, int, int]]]:
    nodes = triangulation.Nodes()
    tris = triangulation.Triangles()
    out_tris: List[Tuple[int, int, int]] = []
    for i in range(int(triangulation.NbTriangles())):
        tri = tris.Value(i + 1)
        if hasattr(tri, "Get"):
            a, b, c = tri.Get()
        else:
            a = tri.Value(1)
            b = tri.Value(2)
            c = tri.Value(3)
        out_tris.append((int(a), int(b), int(c)))
    return nodes, out_tris


def _vertex_key(point: Sequence[float], *, tol: float) -> Tuple[int, int, int]:
    p = np.asarray(point, dtype=np.float64)
    scale = max(float(tol), 1e-9)
    return (
        int(np.rint(p[0] / scale)),
        int(np.rint(p[1] / scale)),
        int(np.rint(p[2] / scale)),
    )


def _extract_face_triangulation(faces, face_map, *, deflection: float):
    from OCC.Core.BRep import BRep_Tool  # type: ignore
    from OCC.Core.TopLoc import TopLoc_Location  # type: ignore

    vertices: List[np.ndarray] = []
    faces_out: List[Tuple[int, int, int]] = []
    tri_face_id: List[int] = []
    vkey_to_idx: Dict[Tuple[int, int, int], int] = {}
    tol = max(float(deflection) * 0.25, 1e-6)

    for face in faces:
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation(face, loc)
        if tri is None or bool(tri.IsNull()):
            continue
        trsf = loc.Transformation()
        nodes, tri_ids = _tri_nodes_and_indices(tri)
        if not tri_ids:
            continue

        global_face_idx = int(face_map.FindIndex(face)) - 1
        local_to_global: Dict[int, int] = {}
        for local_idx in range(int(tri.NbNodes())):
            p = nodes.Value(local_idx + 1).Transformed(trsf)
            xyz = np.array([float(p.X()), float(p.Y()), float(p.Z())], dtype=np.float64)
            key = _vertex_key(xyz, tol=tol)
            mapped = vkey_to_idx.get(key)
            if mapped is None:
                mapped = len(vertices)
                vertices.append(xyz)
                vkey_to_idx[key] = mapped
            local_to_global[int(local_idx + 1)] = int(mapped)

        for a, b, c in tri_ids:
            ga = local_to_global.get(int(a))
            gb = local_to_global.get(int(b))
            gc = local_to_global.get(int(c))
            if ga is None or gb is None or gc is None:
                continue
            if ga == gb or gb == gc or ga == gc:
                continue
            faces_out.append((ga, gb, gc))
            tri_face_id.append(global_face_idx)

    if not vertices or not faces_out:
        raise RuntimeError("B-Rep tessellation produced no valid triangles.")

    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces_out, dtype=np.int64)
    tri_face = np.asarray(tri_face_id, dtype=np.int64)

    # Remove duplicate triangles created by meshing artifacts while keeping face IDs aligned.
    canonical = np.sort(f, axis=1)
    _, unique_idx = np.unique(canonical, axis=0, return_index=True)
    keep = np.sort(unique_idx)
    f = f[keep]
    tri_face = tri_face[keep]

    mins = v.min(axis=0)
    maxs = v.max(axis=0)
    bbox = (float(mins[0]), float(mins[1]), float(mins[2]), float(maxs[0]), float(maxs[1]), float(maxs[2]))
    return v, f, tri_face, bbox


def _extract_edge_polylines(edges, *, deflection: float) -> Dict[int, np.ndarray]:
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve  # type: ignore
    from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection  # type: ignore
    from OCC.Core.TopLoc import TopLoc_Location  # type: ignore

    out: Dict[int, np.ndarray] = {}
    lin = max(float(deflection), 1e-4)

    for edge_idx, edge in enumerate(edges):
        pts: List[np.ndarray] = []
        try:
            adaptor = BRepAdaptor_Curve(edge)
            sampler = GCPnts_QuasiUniformDeflection(adaptor, lin)
            if bool(sampler.IsDone()) and int(sampler.NbPoints()) >= 2:
                for i in range(1, int(sampler.NbPoints()) + 1):
                    p = sampler.Value(i)
                    pts.append(np.array([float(p.X()), float(p.Y()), float(p.Z())], dtype=np.float64))
        except Exception:
            pts = []

        if len(pts) < 2:
            # Fallback: sample edge end parameters from the adaptor itself.
            try:
                adaptor = BRepAdaptor_Curve(edge)
                u0 = float(adaptor.FirstParameter())
                u1 = float(adaptor.LastParameter())
                ts = np.linspace(u0, u1, 12, dtype=np.float64)
                pts = []
                for t in ts:
                    p = adaptor.Value(float(t))
                    pts.append(np.array([float(p.X()), float(p.Y()), float(p.Z())], dtype=np.float64))
            except Exception:
                pts = []

        if len(pts) < 2:
            out[int(edge_idx)] = np.empty((0, 3), dtype=np.float64)
            continue

        arr = np.asarray(pts, dtype=np.float64)
        # Keep monotonic-ish polyline and remove duplicates.
        dedup = [arr[0]]
        for p in arr[1:]:
            if float(np.linalg.norm(p - dedup[-1])) > 1e-9:
                dedup.append(p)
        out[int(edge_idx)] = np.asarray(dedup, dtype=np.float64)
    return out


def _extract_face_boundary_edge_ids(faces, edge_map) -> Dict[int, List[int]]:
    from OCC.Core.TopAbs import TopAbs_EDGE  # type: ignore
    from OCC.Core.TopExp import TopExp_Explorer  # type: ignore
    from OCC.Core.TopoDS import topods  # type: ignore

    out: Dict[int, List[int]] = {}
    for face_idx, face in enumerate(faces):
        ids: List[int] = []
        exp = TopExp_Explorer(face, TopAbs_EDGE)
        while exp.More():
            edge = topods.Edge(exp.Current())
            eid = int(edge_map.FindIndex(edge)) - 1
            if eid >= 0:
                ids.append(eid)
            exp.Next()
        out[int(face_idx)] = sorted(set(ids))
    return out


def _detect_units_label(ext: str) -> str:
    # STEP and IGES units can be queried from Interface_Static in many OCC builds.
    try:
        from OCC.Core.Interface import Interface_Static  # type: ignore

        keys = ["xstep.cascade.unit", "write.step.unit", "xstep.unit"]
        if ext in {".iges", ".igs"}:
            keys = ["xstep.cascade.unit", "xstep.unit", "write.step.unit"]
        for key in keys:
            try:
                value = str(Interface_Static.CVal(key)).strip()
            except Exception:
                value = ""
            if value:
                return value
    except Exception:
        pass
    return "unknown"
