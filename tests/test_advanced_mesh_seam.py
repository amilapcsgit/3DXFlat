from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import numpy as np

from qt_app import mesh_cutting


Edge = Tuple[int, int]


def _norm_edge(edge: Sequence[int]) -> Edge:
    a = int(edge[0])
    b = int(edge[1])
    return (a, b) if a < b else (b, a)


def _toggle_manual_edge(
    cuts: set[Edge],
    anchor: Edge | None,
    edge: Sequence[int],
    *,
    shift: bool = False,
) -> tuple[set[Edge], Edge | None]:
    out = set(cuts)
    normalized = _norm_edge(edge)
    if shift:
        out.discard(normalized)
        return out, normalized
    if anchor is not None and normalized == _norm_edge(anchor):
        return out, anchor
    if normalized in out:
        out.discard(normalized)
    else:
        out.add(normalized)
    return out, anchor


def test_selected_patch_boundary_toggle_is_deterministic_and_camera_independent():
    # Simple rectangular patch triangulated in two faces.
    faces = np.array(
        [
            [0, 1, 2],
            [0, 2, 3],
        ],
        dtype=np.int64,
    )
    selected = np.array([0, 1], dtype=np.int64)

    boundary = mesh_cutting.extract_mesh_candidate_edges(faces, face_indices=selected, boundary_only=True)
    boundary_set = {_norm_edge(e) for e in boundary}
    assert boundary_set == {(0, 1), (1, 2), (2, 3), (0, 3)}

    # Same toggling sequence, regardless of "camera state" labels.
    sequence: Iterable[tuple[Edge, bool]] = [
        ((0, 1), False),
        ((2, 3), False),
        ((0, 1), False),  # toggle off
        ((1, 2), True),   # set anchor
        ((1, 2), False),  # cut toggle blocked by anchor conflict
        ((0, 3), False),
    ]

    camera_states = ["top", "front", "right", "iso"]
    results = []
    for _camera in camera_states:
        cuts: set[Edge] = set()
        anchor: Edge | None = None
        for edge, shift in sequence:
            assert _norm_edge(edge) in boundary_set
            cuts, anchor = _toggle_manual_edge(cuts, anchor, edge, shift=shift)
        results.append((frozenset(cuts), anchor))

    assert all(result == results[0] for result in results[1:])
    assert results[0][0] == frozenset({(0, 3), (2, 3)})
    assert results[0][1] == (1, 2)
