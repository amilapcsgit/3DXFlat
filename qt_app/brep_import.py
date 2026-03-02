from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Dict, List, Sequence, Tuple

import numpy as np

_OCC_RUNTIME_READY = False
_OCC_DLL_HANDLES: List[object] = []


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


def _iter_occ_prefix_candidates() -> List[Path]:
    candidates: List[Path] = []

    def _push(value: str | None) -> None:
        if not value:
            return
        p = Path(value).expanduser()
        if p not in candidates:
            candidates.append(p)

    # Primary prefixes exported by launcher.
    _push(os.environ.get("MAMBA_ENV_PREFIX"))
    _push(os.environ.get("THREEDXFLAT_OCC_PREFIX"))

    # Current local bootstrap defaults.
    user_home = Path.home()
    _push(str(user_home / "3DXF" / "e312"))
    _push(str(user_home / "3DXF" / "e312b"))
    _push(str(user_home / "AppData" / "Local" / "3DXFlat" / "micromamba-env-py312"))

    return candidates


def _ensure_occ_runtime() -> None:
    global _OCC_RUNTIME_READY
    if _OCC_RUNTIME_READY:
        return

    # The launcher keeps OCC package copies in a dedicated overlay path.
    overlay = os.environ.get("OCC_OVERLAY_SITE")
    if overlay:
        overlay_path = str(Path(overlay).expanduser())
        if overlay_path and overlay_path not in sys.path:
            sys.path.insert(0, overlay_path)

    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        for prefix in _iter_occ_prefix_candidates():
            for sub in ("Library/bin", "DLLs", "bin"):
                dll_dir = prefix / sub
                if not dll_dir.exists():
                    continue
                try:
                    handle = os.add_dll_directory(str(dll_dir))
                except Exception:
                    continue
                _OCC_DLL_HANDLES.append(handle)

    _OCC_RUNTIME_READY = True


def is_occ_available() -> Tuple[bool, str | None]:
    _ensure_occ_runtime()
    try:
        # Validate with real STEP/IGES modules, not just OCC.Core package import.
        from OCC.Core.IFSelect import IFSelect_RetDone  # type: ignore  # noqa: F401
        from OCC.Core.STEPControl import STEPControl_Reader  # type: ignore  # noqa: F401
        from OCC.Core.IGESControl import IGESControl_Reader  # type: ignore  # noqa: F401
    except Exception as exc:
        return False, str(exc)
    return True, None


def load_brep(path: str, *, deflection: float = 0.6, angle_rad: float = 0.35) -> BrepModel:
    _ensure_occ_runtime()
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
    from OCC.Core.TopExp import TopExp_Explorer, topexp_MapShapes  # type: ignore
    from OCC.Core.TopTools import TopTools_IndexedMapOfShape  # type: ignore
    from OCC.Core.TopoDS import topods  # type: ignore

    face_map = TopTools_IndexedMapOfShape()
    edge_map = TopTools_IndexedMapOfShape()
    topexp_MapShapes(shape, TopAbs_FACE, face_map)
    topexp_MapShapes(shape, TopAbs_EDGE, edge_map)

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


def _tri_node(triangulation, index_1based: int):
    if hasattr(triangulation, "Node"):
        return triangulation.Node(int(index_1based))
    nodes = triangulation.Nodes()
    return nodes.Value(int(index_1based))


def _tri_indices(triangulation) -> List[Tuple[int, int, int]]:
    out_tris: List[Tuple[int, int, int]] = []
    nb_tri = int(triangulation.NbTriangles())
    for i in range(1, nb_tri + 1):
        if hasattr(triangulation, "Triangle"):
            tri = triangulation.Triangle(i)
        else:
            tris = triangulation.Triangles()
            tri = tris.Value(i)
        if hasattr(tri, "Get"):
            a, b, c = tri.Get()
        else:
            a = tri.Value(1)
            b = tri.Value(2)
            c = tri.Value(3)
        out_tris.append((int(a), int(b), int(c)))
    return out_tris


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
        if tri is None:
            continue
        if hasattr(tri, "IsNull") and bool(tri.IsNull()):
            continue
        trsf = loc.Transformation()
        tri_ids = _tri_indices(tri)
        if not tri_ids:
            continue

        global_face_idx = int(face_map.FindIndex(face)) - 1
        local_to_global: Dict[int, int] = {}
        for local_idx in range(1, int(tri.NbNodes()) + 1):
            p = _tri_node(tri, local_idx).Transformed(trsf)
            xyz = np.array([float(p.X()), float(p.Y()), float(p.Z())], dtype=np.float64)
            key = _vertex_key(xyz, tol=tol)
            mapped = vkey_to_idx.get(key)
            if mapped is None:
                mapped = len(vertices)
                vertices.append(xyz)
                vkey_to_idx[key] = mapped
            local_to_global[int(local_idx)] = int(mapped)

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
