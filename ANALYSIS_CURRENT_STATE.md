# Current State Analysis (No Fixes Applied)

Date: 2026-02-09
Project: `3DXFlat`

## Scope
- Analyze current working version behavior only.
- Do not change flattening logic in this step.
- Capture known issues before next improvement cycle.

## Reproduction Inputs
- `C:\Users\Amilapcs\Downloads\6mm_QuonsetHut1B_Hexless.stl`
- `C:\Users\Amilapcs\Downloads\desert_hut.stl`

## Observations
1. GUI is operational:
- Viewer is movable (rotate/pan/zoom/home).
- Surface dropdown and Prev/Next selection work.
- DXF export succeeds and is non-empty.

2. Surface extraction is heuristic and can return complex patches:
- `load_with_components` can return many extracted patches for watertight meshes.
- Current ranking is only by area (`flatten_surface/import_export.py:73`), so top candidates may be geometrically complex for production.

3. Some selected surfaces flatten to visually unexpected outlines:
- Complex patches can produce outlines that appear as multi-lobed/cross-like or with small loops in CAD.
- This is not necessarily a write failure; it is usually a patch-selection/topology issue.

4. Metrics confirm this behavior:
- For `desert_hut.stl`, selected large patch (`~357k faces`):
  - area error: `~1.20%`
  - perimeter error: `~3.77%`
- This aligns with the GUI screenshot and indicates a usable but not yet production-final perimeter fidelity.

## Technical Findings
1. Patch generation strategy (major):
- `_extract_open_patches_from_watertight` builds candidates using face-normal directional thresholds (`flatten_surface/import_export.py:32`).
- This can produce mathematically open patches that are not equivalent to a manufacturing panel boundary.

2. Candidate ordering (major):
- Candidates are sorted by area only (`flatten_surface/import_export.py:73`).
- No scoring for:
  - single outer loop preference,
  - low boundary complexity,
  - low curvature variance,
  - low flattening distortion forecast.

3. Export semantics (major):
- DXF export writes all returned boundary loops as independent `LWPOLYLINE` entities.
- If a patch includes holes/islands, CAD shows all loops exactly as generated.
- No explicit outer/inner loop classification for CAM intent yet.

4. Accuracy reporting limits (moderate):
- Current metrics are global area/perimeter error (`flatten_surface/flatten_surface.py:27`).
- No local strain map thresholding for pass/fail criteria at panel edges.

5. UI/preview scaling (moderate):
- Preview decimates faces for speed (`gui.py:194`) but flattening uses full mesh.
- This is expected, but users may interpret preview smoothness as manufacturing validity.

## Data Snapshot (desert_hut candidates)
- `load_with_components` returned `16` selectable surfaces.
- Example top candidates showed wide topology variance (single-loop and multi-loop patches).
- This confirms the need for a quality-ranked panel selection strategy.

## Conclusion
Current version is a working baseline:
- app runs,
- viewer interaction works,
- surface selection works,
- DXF export is functional.

But production reliability is not guaranteed on every selected surface due to patch selection heuristics and missing manufacturability ranking.

## Next Phase (after this branch push)
1. Add candidate quality scoring (loop count, complexity, distortion pre-check).
2. Prefer single-loop panel candidates by default.
3. Add explicit warnings for high perimeter error and multi-loop outputs.
4. Add optional seam/cut-line workflow for SolidWorks-like control.
