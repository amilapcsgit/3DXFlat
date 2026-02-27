from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from qt_app.edge_selection import (
    build_edge_chains,
    build_selected_submesh,
    chain_length_from_polylines,
    compute_patch_boundary_edges,
    fallback_pick_edge_on_triangle,
    screen_space_pick_edge,
    screen_space_pick_polyline_chain,
)
from qt_app.mesh_io import load_mesh_file


def _load_reference_mesh():
    path = Path(__file__).resolve().parents[1] / "data" / "ProvaFunzioneTelo.STL"
    if not path.exists():
        pytest.skip("Reference STL not found: data/ProvaFunzioneTelo.STL")
    mesh = load_mesh_file(str(path))
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    return mesh


def test_boundary_extraction_non_empty_for_selected_patch():
    mesh = _load_reference_mesh()
    faces = np.asarray(mesh.faces, dtype=np.int64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    if len(faces) == 0:
        pytest.skip("Reference mesh has no faces.")

    selected = np.where(normals[:, 2] > 0.25)[0]
    if len(selected) < 32:
        selected = np.argsort(normals[:, 2])[::-1][: max(32, min(512, len(faces)))]
    sub = build_selected_submesh(faces, selected.tolist())
    boundary_edges = compute_patch_boundary_edges(sub["faces_sub"])
    assert len(boundary_edges) > 0


def test_screen_space_pick_edge_synthetic():
    vertices = np.array(
        [
            [-0.5, -0.5, 0.0],
            [0.5, -0.5, 0.0],
            [0.5, 0.5, 0.0],
            [-0.5, 0.5, 0.0],
        ],
        dtype=np.float64,
    )
    edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
    viewproj = np.eye(4, dtype=np.float64)
    picked = screen_space_pick_edge((100.0, 52.0), edges, vertices, viewproj, viewport_w=200, viewport_h=200, px_tol=8.0)
    assert picked == (2, 3)


def test_fallback_pick_edge_on_triangle():
    tri_edges = [
        ((10.0, 10.0), (100.0, 10.0), "ab"),
        ((100.0, 10.0), (60.0, 80.0), "bc"),
        ((60.0, 80.0), (10.0, 10.0), "ca"),
    ]
    picked = fallback_pick_edge_on_triangle((56.0, 78.0), tri_edges, px_tol=12.0)
    assert picked == "ca"


def test_build_edge_chains_open_component():
    edge_polylines = {
        10: np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64),
        11: np.array([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float64),
        12: np.array([[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float64),
    }
    chains = build_edge_chains([10, 11, 12], edge_polylines)
    assert len(chains) == 1
    assert tuple(chains[0]) == (10, 11, 12)
    length = chain_length_from_polylines(chains[0], edge_polylines)
    assert pytest.approx(length, rel=1e-6, abs=1e-6) == 3.0


def test_screen_space_pick_polyline_chain():
    edge_polylines = {
        1: np.array([[-0.8, 0.2, 0.0], [-0.2, 0.2, 0.0]], dtype=np.float64),
        2: np.array([[0.2, -0.5, 0.0], [0.2, 0.5, 0.0]], dtype=np.float64),
    }
    chains = [(1,), (2,)]
    viewproj = np.eye(4, dtype=np.float64)
    picked = screen_space_pick_polyline_chain(
        mouse_xy=(120.0, 82.0),
        chains=chains,
        edge_polylines=edge_polylines,
        viewproj=viewproj,
        viewport_w=200,
        viewport_h=200,
        px_tol=12.0,
    )
    assert picked == (1,)
