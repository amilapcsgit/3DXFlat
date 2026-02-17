import numpy as np


def compute_face_area_strain_percent(vertices, faces, unwrap):
    original_edges = vertices[faces[:, [1, 2, 0]]] - vertices[faces[:, [0, 1, 2]]]
    unfolded_edges = unwrap[faces[:, [1, 2, 0]]] - unwrap[faces[:, [0, 1, 2]]]
    original_areas = 0.5 * np.linalg.norm(np.cross(original_edges[:, 0], original_edges[:, 1]), axis=1)
    unfolded_areas = 0.5 * np.abs(np.cross(unfolded_edges[:, 0], unfolded_edges[:, 1]))
    positive = original_areas[original_areas > 0]
    area_floor = 1e-12 if len(positive) == 0 else max(float(np.percentile(positive, 5)) * 0.1, 1e-12)
    denom = np.maximum(original_areas, area_floor)
    return 100.0 * np.abs(unfolded_areas - original_areas) / denom


def compute_deformation(vertices, faces, unwrap, verbose=True):
    strain_percent = compute_face_area_strain_percent(vertices, faces, unwrap)
    original_edges = vertices[faces[:, [1, 2, 0]]] - vertices[faces[:, [0, 1, 2]]]
    unfolded_edges = unwrap[faces[:, [1, 2, 0]]] - unwrap[faces[:, [0, 1, 2]]]
    original_areas = 0.5 * np.linalg.norm(np.cross(original_edges[:, 0], original_edges[:, 1]), axis=1)
    unfolded_areas = 0.5 * np.abs(np.cross(unfolded_edges[:, 0], unfolded_edges[:, 1]))
    area_2d = float(np.sum(unfolded_areas))
    area_3d = float(np.sum(original_areas))
    area_diff = area_3d - area_2d

    if verbose:
        print(f"3D Area: {area_3d} mm^2")
        print(f"2D Area: {area_2d} mm^2")
        print(f"Diff Area: {area_diff} mm^2")

    return strain_percent
