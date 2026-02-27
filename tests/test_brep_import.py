from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from qt_app.brep_import import is_occ_available, load_brep


def test_load_brep_step_smoke_optional_occ():
    ok, _ = is_occ_available()
    if not ok:
        pytest.skip("pythonocc-core is not available")

    path = Path(__file__).resolve().parents[1] / "data" / "ProvaFunzioneTelo.STEP"
    if not path.exists():
        pytest.skip("Reference STEP file not found: data/ProvaFunzioneTelo.STEP")

    model = load_brep(str(path))
    v = np.asarray(model.tri_mesh_vertices, dtype=np.float64)
    f = np.asarray(model.tri_mesh_faces, dtype=np.int64)
    tri_face = np.asarray(model.tri_face_id, dtype=np.int64)

    assert v.ndim == 2 and v.shape[1] == 3 and len(v) > 0
    assert f.ndim == 2 and f.shape[1] == 3 and len(f) > 0
    assert tri_face.ndim == 1 and len(tri_face) == len(f)
    assert len(model.faces) > 0
    assert len(model.edges) > 0
    assert len(model.face_boundary_edge_ids) > 0
