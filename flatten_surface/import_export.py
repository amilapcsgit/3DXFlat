import numpy as np
import svgwrite
import trimesh
import ezdxf
from ezdxf import units
from pathlib import Path


def _load_mesh(path):
    mesh = trimesh.load(path)
    if isinstance(mesh, trimesh.Scene):
        if len(mesh.geometry) > 1:
            mesh = mesh.dump(concatenate=True)
        elif len(mesh.geometry) == 1:
            mesh = list(mesh.geometry.values())[0]
        else:
            raise ValueError("Empty 3D file")
    return mesh


def _has_boundary_edges(faces):
    if len(faces) == 0:
        return False
    edges = np.vstack((
        faces[:, [0, 1]],
        faces[:, [1, 2]],
        faces[:, [2, 0]],
    ))
    edges = np.sort(edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return np.any(counts == 1)


def _topology_counts(faces):
    if len(faces) == 0:
        return {"open_edges": 0, "non_manifold_edges": 0}
    edges = np.vstack((
        faces[:, [0, 1]],
        faces[:, [1, 2]],
        faces[:, [2, 0]],
    ))
    edges = np.sort(edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return {
        "open_edges": int(np.sum(counts == 1)),
        "non_manifold_edges": int(np.sum(counts > 2)),
    }


def _extract_open_patches_from_watertight(mesh, min_faces=200):
    directions = np.array([
        [1.0, 0.0, 0.0],
        [-1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, -1.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, -1.0],
    ], dtype=np.float64)
    thresholds = (0.00, 0.05, 0.10, 0.20, 0.30)

    candidates = []
    seen = set()
    face_normals = np.asarray(mesh.face_normals, dtype=np.float64)

    for threshold in thresholds:
        for direction in directions:
            selected_faces = np.where(face_normals @ direction > threshold)[0]
            if len(selected_faces) < min_faces:
                continue

            submesh = mesh.submesh([selected_faces], append=True, repair=False)
            for part in submesh.split(only_watertight=False):
                if len(part.faces) < min_faces:
                    continue

                part_faces = np.asarray(part.faces, dtype=np.int64)
                if not _has_boundary_edges(part_faces):
                    continue

                signature = (
                    int(len(part.faces)),
                    round(float(part.area), 3),
                    tuple(np.round(np.asarray(part.bounds).reshape(-1), 2)),
                )
                if signature in seen:
                    continue

                seen.add(signature)
                candidates.append(part)

    candidates.sort(key=lambda m: m.area, reverse=True)
    return candidates[:16]


def load(path, prefer_open_surface=True):
    mesh = _load_mesh(path)

    if prefer_open_surface and mesh.is_watertight:
        extracted_patches = _extract_open_patches_from_watertight(mesh)
        if extracted_patches:
            mesh = extracted_patches[0]

    return (
        np.array(mesh.vertices, dtype=np.float64),
        np.array(mesh.faces, dtype=np.int64),
    )


def load_with_components(path):
    mesh = _load_mesh(path)
    components = mesh.split(only_watertight=False)
    components.sort(key=lambda m: m.area, reverse=True)

    open_components = [m for m in components if _has_boundary_edges(np.asarray(m.faces, dtype=np.int64))]
    if open_components:
        return open_components

    if mesh.is_watertight:
        patches = _extract_open_patches_from_watertight(mesh)
        if patches:
            return patches

    return components


def extract_source_label(path):
    p = Path(path)
    object_name = p.stem
    material_name = ""
    try:
        loaded = trimesh.load(path)
        if isinstance(loaded, trimesh.Scene):
            if loaded.geometry:
                first_key = next(iter(loaded.geometry.keys()))
                object_name = first_key or object_name
                first_geom = loaded.geometry[first_key]
                material_name = getattr(getattr(first_geom.visual, "material", None), "name", "") or ""
        else:
            object_name = loaded.metadata.get("name", object_name) if hasattr(loaded, "metadata") else object_name
            material_name = getattr(getattr(loaded.visual, "material", None), "name", "") or ""
    except Exception:
        pass
    label = object_name if not material_name else f"{object_name} | {material_name}"
    return {"object_name": object_name, "material_name": material_name, "label": label}


def component_quality(mesh):
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)

    topo = _topology_counts(faces)
    if len(faces) > 0:
        tri = vertices[faces]
        tri_area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        degenerate_faces = int(np.sum(tri_area < 1e-12))
    else:
        degenerate_faces = 0

    return {
        "faces": int(len(faces)),
        "area": float(mesh.area),
        "is_watertight": bool(mesh.is_watertight),
        "open_edges": topo["open_edges"],
        "non_manifold_edges": topo["non_manifold_edges"],
        "degenerate_faces": degenerate_faces,
    }


def mesh_to_data(mesh):
    return (
        np.array(mesh.vertices, dtype=np.float64),
        np.array(mesh.faces, dtype=np.int64),
    )


def get_unit_scale(unit_name):
    """Returns scale factor to convert given unit to mm."""
    scales = {
        "mm": 1.0,
        "cm": 10.0,
        "m": 1000.0,
        "inch": 25.4,
    }
    return scales.get(unit_name.lower(), 1.0)


def export_svg(unwrap, bounds, path_svg, scale=1.0):
    contours = [unwrap[bound] * scale for bound in bounds]

    min_x = float("inf")
    min_y = float("inf")

    for contour in contours:
        x, y = contour.T
        min_x = min(min_x, np.min(x))
        min_y = min(min_y, np.min(y))

    for i, contour in enumerate(contours):
        x, y = contour.T
        x -= min_x
        y -= min_y
        contours[i] = np.array([x, y]).T

    dwg = svgwrite.Drawing(path_svg, profile="tiny")
    for contour in contours:
        path_data = "M" + " L".join(f"{x},{y}" for x, y in contour) + " Z"
        dwg.add(dwg.path(d=path_data, fill="none", stroke="black"))
    dwg.save()


def _loop_area(points):
    if len(points) < 3:
        return 0.0
    x = points[:, 0]
    y = points[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - y * np.roll(x, -1)))


def _rotate_xy(points, angle_rad, center):
    c = float(np.cos(angle_rad))
    s = float(np.sin(angle_rad))
    rot = np.array([[c, -s], [s, c]], dtype=np.float64)
    return (points - center) @ rot.T + center


def _get_alignment_transform(loops):
    if not loops:
        return None, None
    try:
        from shapely.geometry import Polygon
    except Exception:
        return None, None

    areas = [abs(_loop_area(loop)) for loop in loops]
    outer = loops[int(np.argmax(areas))]
    poly = Polygon(outer)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None, None

    mrr = poly.minimum_rotated_rectangle
    coords = np.asarray(mrr.exterior.coords[:-1], dtype=np.float64)
    if len(coords) < 2:
        return None, None
    edges = np.roll(coords, -1, axis=0) - coords
    lengths = np.linalg.norm(edges, axis=1)
    idx = int(np.argmax(lengths))
    edge = edges[idx]
    angle = np.arctan2(edge[1], edge[0])
    center = np.asarray(poly.centroid.coords[0], dtype=np.float64)
    return -angle, center


def _apply_alignment(loops, angle, center):
    if angle is None or center is None:
        return loops
    return [_rotate_xy(loop, angle, center) for loop in loops]


def _offset_outer_loop(loops, seam_allowance_mm):
    if seam_allowance_mm <= 0 or not loops:
        return None
    try:
        from shapely.geometry import Polygon, MultiPolygon
    except Exception as exc:
        raise RuntimeError("Shapely is required for seam allowance offset. Install shapely.") from exc

    areas = [abs(_loop_area(loop)) for loop in loops]
    outer = loops[int(np.argmax(areas))]
    poly = Polygon(outer)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None

    offset = poly.buffer(float(seam_allowance_mm), join_style=2)
    if offset.is_empty:
        return None
    if isinstance(offset, MultiPolygon):
        offset = max(offset.geoms, key=lambda g: g.area)

    exterior = np.asarray(offset.exterior.coords, dtype=np.float64)
    if len(exterior) < 3:
        return None
    return exterior


def export_dxf(
    unwrap,
    bounds,
    path_dxf,
    scale=1.0,
    seam_allowance_mm=0.0,
    align_to_x=False,
    label_text=None,
    relief_cut_path=None,
):
    doc = ezdxf.new("R2000")
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    msp = doc.modelspace()

    contours = [unwrap[bound] * scale for bound in bounds]
    contours = [np.asarray(c, dtype=np.float64) for c in contours if len(c) >= 3]
    relief_path = None
    if relief_cut_path is not None and len(relief_cut_path) >= 2:
        relief_path = np.asarray(relief_cut_path, dtype=np.float64) * scale

    if align_to_x:
        angle, center = _get_alignment_transform(contours)
        contours = _apply_alignment(contours, angle, center)
        if relief_path is not None:
            relief_path = _rotate_xy(relief_path, angle, center)

    if "FOLD_LINE" not in doc.layers:
        doc.layers.add("FOLD_LINE", dxfattribs={"color": 5})
    if "CUT_LINE" not in doc.layers:
        doc.layers.add("CUT_LINE", dxfattribs={"color": 1})
    if "LABELS" not in doc.layers:
        doc.layers.add("LABELS", dxfattribs={"color": 3})
    if "RELIEF_CUT" not in doc.layers:
        doc.layers.add("RELIEF_CUT", dxfattribs={"color": 2})

    for contour in contours:
        points = [(float(p[0]), float(p[1])) for p in contour]
        msp.add_lwpolyline(points, dxfattribs={"layer": "FOLD_LINE"}, close=True)

    cut_loop = _offset_outer_loop(contours, seam_allowance_mm)
    if cut_loop is not None:
        cut_points = [(float(p[0]), float(p[1])) for p in cut_loop]
        msp.add_lwpolyline(cut_points, dxfattribs={"layer": "CUT_LINE"}, close=True)
    elif contours:
        # If no seam allowance, cut line equals the first contour.
        cut_points = [(float(p[0]), float(p[1])) for p in contours[0]]
        msp.add_lwpolyline(cut_points, dxfattribs={"layer": "CUT_LINE"}, close=True)

    if label_text and contours:
        center = np.mean(contours[0], axis=0)
        mtext = msp.add_mtext(
            str(label_text),
            dxfattribs={"layer": "LABELS", "char_height": max(5.0, 0.015 * np.ptp(contours[0][:, 0]))},
        )
        mtext.set_location((float(center[0]), float(center[1])), attachment_point=5)

    if relief_path is not None:
        relief_points = [(float(p[0]), float(p[1])) for p in relief_path]
        msp.add_lwpolyline(relief_points, dxfattribs={"layer": "RELIEF_CUT"}, close=False)

    doc.saveas(path_dxf)
