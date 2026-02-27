from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

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
    raise NotImplementedError(
        "B-Rep loader is not wired yet. Install pythonocc-core and continue with Phase 2 implementation."
    )
