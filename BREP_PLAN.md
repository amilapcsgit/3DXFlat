# B-Rep Integration Plan (Branch: B-rep)

## Goal

Add native CAD B-Rep import (STEP/IGES via OpenCascade bindings) so 3DXFlat can select real CAD faces and edges with SolidWorks-like semantics, while keeping the existing triangle-based flatten pipeline.

## Current Touchpoints (Source of Truth)

- Model import entry:
  - `qt_app/ribbon_window.py`
    - `RibbonMainWindow.import_3d_dialog()`
    - `RibbonMainWindow.load_model_file()`
    - `Worker._run_load_model()`
- Existing mesh file loader:
  - `qt_app/mesh_io.py`
- Viewport selection and seam UX:
  - `qt_app/viewport.py`
    - raycast face picking
    - selected faces state
    - seam candidate edges + hover/click edge picking
    - anchor/cut edge state and overlays
- Seam cut topology processing:
  - `qt_app/mesh_cutting.py`
- Flatten pipeline wiring:
  - `qt_app/ribbon_window.py`
    - `_flatten_faces_payload()`
    - `run_flatten()`
    - `Worker._run_flatten()`

## Integration Strategy

1. Keep flatten solver input unchanged: triangles `(V, F)`.
2. Add a B-Rep import module that returns:
   - CAD topology metadata (stable face IDs, edge IDs, boundary map),
   - tessellated mesh `(V, F)` for rendering/picking/flatten,
   - mapping `tri_face_id` from each triangle to CAD face.
3. Add runtime capability detection for optional `pythonocc-core`.
4. Preserve STL/OBJ behavior exactly.

## Proposed New Structures

- New module: `qt_app/brep_import.py`
  - `is_occ_available() -> tuple[bool, str | None]`
  - `load_brep(path: str, deflection: float, angle_rad: float) -> BrepModel`
  - `BrepModel` dataclass:
    - `source_path`
    - `shape`
    - `faces`
    - `edges`
    - `tri_mesh_vertices`
    - `tri_mesh_faces`
    - `tri_face_id`
    - `edge_polylines`
    - `face_boundary_edge_ids`
    - `bbox`
    - `units_label`

## Runtime Model State (UI)

Store active model state in `RibbonMainWindow` and pass into viewport:

- `active_model_type`: `"mesh"` or `"brep"`
- `active_brep`: optional BRep metadata dict

Viewport gains optional B-Rep metadata:

- `brep_tri_face_id`: maps picked triangle index to CAD face ID
- `brep_face_boundary_edge_ids`
- `brep_edge_polylines`
- edge chain structures for SolidWorks-like border/cut chain toggling

## Phase Breakdown

1. Optional dependency + capability detection.
2. STEP/IGES loader with tessellation + face/edge maps.
3. Import dialog and B-Rep face selection semantics.
4. B-Rep edge-chain seam selection semantics.
5. Map selected B-Rep chains into existing mesh-cut flatten flow.
6. Docs, checks, and optional tests.

## Risks / Constraints

- `pythonocc-core` availability differs by environment and Python version.
- OpenGL may be unavailable in Hyper-V; B-Rep loading must still succeed and not crash.
- Tessellation quality impacts chain mapping stability.
- Chain-to-mesh-edge mapping needs tolerance-based matching for robustness.

## Validation Plan

- Mandatory per phase:
  - `python -m py_compile` on changed modules
- Targeted tests:
  - unit tests for chain extraction/picking in pure Python modules
  - optional `brep_import` smoke test (skip if OCC unavailable)
- Manual smoke:
  - import STL still works
  - import STEP/IGES reports clear message if OCC missing
  - CAD face count and selection increments by CAD face IDs
