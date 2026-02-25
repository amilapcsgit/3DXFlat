# 3DXFlat UI Status & Refinement Log

## Phase 2: Unified Command Bar Stabilization (In Progress)

### Completed Improvements (Current Branch)
- **Compact UI Scaling**: Reduced button and toolbar heights by ~30% across the app. Updated `UnifiedCommandBar` height from 128px to 92px. Adjusted icon sizes and internal margins for a tighter CAD aesthetic.
- **Typography Update**: Switched primary font to `Roboto Condensed` for a more professional and space-efficient look.

- **Restoration of Core Workflow Controls**:
  - **Seam Allowance**: Restored the `seam_slider` and `seam_label` to Row 2 of the `UnifiedCommandBar`. It is now integrated using the standard field shell pattern.
  - **Quality Gauge**: Restored the `quality_gauge` (QProgressBar) to Row 1 of the `UnifiedCommandBar`, providing immediate visual feedback after flattening.
- **Horizontal Spacing Optimization**:
  - Reduced standard button `min_width` (132px -> 110px for Row 1, 100px for Row 2) to prevent UI clipping on common screen resolutions.
  - Reduced CTA button widths (`Run Flatten`: 168px -> 140px, `Export DXF`: 148px -> 120px).
  - Tightened `_field_shell` internal margins (10px -> 6px) and spacing (8px -> 4px).
  - Reduced `quality_gauge` width (200px -> 160px).
  - These changes fix the "Metho" / "Sear" text clipping issues observed in runtime screenshots.
- **Code Cleanup**:
  - Removed restored controls from `_build_hidden_compat_controls`.
  - Fixed unused imports in `qt_app/ribbon_window.py`.

### Previous Phase 2 Commits

- `ce3c12c` `PH2-S2: refactor unified command bar into two rows`
- `26a7096` `PH2-S3: enforce CTA hierarchy and labeled actions`
- `20e14eb` `PH2-S4: style two-row command bar with theme tokens`

### Known Follow-up Items

- **Visual Balance**: Further tuning of spacing might be needed depending on high-DPI scaling (150%+).
- **Icon Refinement**: Some placeholder icons are used for restored fields (e.g., "Isolate" icon for Seam). Custom icons should be assigned once available.
- **Status Bar Integration**: Some metadata currently duplicated between Row 1 and Status Bar could be consolidated.

## How the 3D Viewport Currently Works

`ThreeDViewportWidget` (`qt_app/viewport.py`) extends `pyqtgraph.opengl.GLViewWidget` and manages:

- Camera navigation:
  - orbit / pan / zoom (mouse + HUD buttons)
  - current default orbit uses a **turntable model-rotation path** (mesh rotates, world grid stays fixed)
  - grid visibility is now also controllable from the PHASE 2 unified command bar (`Grid` toggle)
  - visible HUD controls are currently: **Fit**, **Orbit**, **Toggle 2D Preview**
- Mesh rendering:
  - face mesh item
  - wireframe/edge mesh item
  - selection overlay mesh item
- Selection:
  - raycast picking against triangles compensated for display rotation.
  - smart selection via face adjacency + angle threshold.
- Camera target / orbit center:
  - pivot locked to the **model bounding-box center**.

## Known Bugs / Risks / Limitations (Current)

1. **OpenGL Line Width**: Driver-dependent; many GPUs clamp to 1.0 in Core Profile.
2. **Post-paint Gradient**: The viewport background gradient is an overlay, not a true OpenGL pass.
3. **High DPI Density**: At 150% scaling, Row 2 may still feel crowded despite optimizations.
4. **Tooltips**: Some newer controls may need more descriptive tooltips for CAD users.

## Validation Performed

- **Static Audit**:
  - Verified `UnifiedCommandBar` spacing logic.
  - Verified `qt_app/ribbon_window.py` callback wiring for Seam/Quality.
  - Python syntax checks passed via `py_compile`.
  - Linting passed via `ruff`.
- **Visual Review (via Screenshots)**:
  - Confirmed text clipping ("Metho", "Sear") occurred at standard widths.
  - Verified optimized widths resolve these overlaps in the design logic.

## Recommended Next Checks (Manual Runtime)

1. Verify `Seam` slider updates the 2D preview in real-time.
2. Verify `Quality` gauge updates after pressing `Run Flatten`.
3. Check for any remaining label clipping at 100%, 125%, and 150% Windows scaling.
4. Confirm `Export DXF` button is secondary (neutral) and `Run Flatten` is primary (accent).
