# UI Status (Current)

## Scope / Context

This repository's UI is **Python**, not C++:

- **Qt bindings:** `PySide6`
- **3D viewport:** `pyqtgraph.opengl.GLViewWidget` (OpenGL-backed)
- **2D preview / nesting canvas:** `QGraphicsView` / `QGraphicsScene`
- **Styling:** global Qt stylesheet (QSS) via `ui/theme/apply_theme.py` + `ui/theme/industrial_cad.qss`

The recent work maps the `dev/specs/ui-enhance-v2.md` C++ `QOpenGLWidget` instructions to the equivalent Python/pyqtgraph implementation.

## Main UI Files (Current)

- `qt_app/ribbon_window.py`
  - Main ribbon-style window shell (top toolbar + tabs + viewport + side panels)
  - Current ribbon follows a singleton-action rule (primary actions live in ribbon tabs)
- `qt_app/unified_command_bar.py`
  - Unified two-row command bar widget (VIEW / SELECT / FLATTEN / OUTPUT groups)
  - Hosts the active command controls in PHASE 2 (icon + label buttons + fields)
- `qt_app/viewport.py`
  - `ThreeDViewportWidget` (3D OpenGL viewport)
  - Mesh load/update, camera orbit/pan/zoom, selection, wireframe/edge rendering
- `ui/theme/apply_theme.py`
  - Builds and applies global app palette + global QSS
- `ui/theme/industrial_cad.qss`
  - Base tokenized theme stylesheet
- `ui/icon_loader.py`
  - Icon loading helpers + `IconRegistry` (resource icons + Base64-backed SVG icon keys)
- `ui/icons/svg_icon.py`
  - SVG icon rendering helpers (now includes inline SVG text -> `QIcon` path)
- `ui/icons/phase3_b64_icons.py`
  - Phase 3 inline Base64 SVG icon constants (Orbit / Import 3D)

## What Was Changed (This Pass)

This file tracks cumulative UI work on branch `ui-enhance`, including the later Phase 3 cleanup and hard refactor pass.

### 1. OpenGL Camera Orbit Fix (model center pivot)

Implemented in `qt_app/viewport.py` (Python equivalent of the C++ `modelCenter` pivot logic):

- Added `_bbox_center(vertices)` helper to compute bounding-box center.
- Updated mesh load path to store bounding-box center instead of vertex mean:
  - `ThreeDViewportWidget.set_mesh(...)`
- Ensured camera-fit / view presets use bounding-box center consistently:
  - `ThreeDViewportWidget._fit_camera_to_mesh()`
  - `ThreeDViewportWidget.apply_view_preset()`

Result:

- Camera orbit pivot is now anchored to the **loaded model's bounding-box center**, not accidental defaults/world origin.

### 2. OpenGL "Headlight" + Wireframe Visibility Fixes

Implemented in `qt_app/viewport.py`:

- Added custom shader program `_CadHeadlightShaderProgram`
  - pyqtgraph-compatible "modern OpenGL" path for headlight behavior
  - uploads camera uniforms every frame (`lightPos`, `viewPos`) using camera position extracted from the **inverted view matrix**
- Added `ThreeDViewportWidget._update_headlight_uniform_state()`
  - called from `paintGL()` before drawing
  - extracts camera world position from `viewMatrix().inverted().column(3)` (spec-equivalent logic)
- Switched face-rendered mesh items to the custom headlight shader:
  - main mesh item
  - selection overlay mesh item
- Wireframe visibility:
  - explicit `glLineWidth(2.0)` for wireframe mesh item in `_CadMeshItem.paint()`
  - existing polygon offset support retained (`glPolygonOffset(...)`) to reduce z-fighting

Result:

- Face shading stays camera-attached (headlight behavior)
- Wireframe is thicker and less likely to visually disappear into the mesh

### 2b. Phase 1 Viewport Navigation + Shading Readability (Follow-up)

Additional work in `qt_app/viewport.py` to address the remaining "glitchy/unintuitive" feel:

- Switched the viewport camera controller from pyqtgraph quaternion orbit to **Euler orbit** (`rotationMethod="euler"`)
  - prevents accumulated roll/"tilted universe" feeling
  - produces a more CAD-like Z-up orbit behavior
- Reworked view presets (`FRONT/BACK/LEFT/RIGHT/TOP/BOTTOM`) to use explicit `elevation`/`azimuth`
  - keeps presets aligned with the Euler controller
- Added **double-click pivot** behavior (historical step)
  - this temporarily allowed double-clicking a visible face to set the orbit pivot to that face centroid
  - later follow-up work (see `4d`) removed this to enforce a fixed bounding-box-center pivot
- Added a **subtle gradient + vignette viewport overlay**
  - improves depth perception and silhouette separation in dark mode
- Upgraded the custom headlight shader to a **two-tone CAD-style readable shader**
  - hemisphere ambient + rim highlight + specular
- Fixed an important regression: `_update_mesh_visuals()` was resetting the mesh shader back to `"shaded"` on every refresh
  - this prevented the custom headlight shader from taking effect consistently

Result:

- Orbit feels more stable and CAD-like
- Note: the temporary double-click pivot behavior from this phase was later removed to preserve a fixed model-center pivot
- Mesh remains more readable in dark mode and under rotation

### 2c. World-Tilt Fix (Turntable Model Rotation, Grid Stays Fixed)

Additional viewport interaction changes in `qt_app/viewport.py` to address the remaining "whole world tilts" problem:

- Orbit drag now uses a **turntable model rotation** path by default
  - the **mesh**, **wireframe**, and **selection overlay** are rotated as display items
  - the **camera** is no longer the primary thing rotating during orbit drag
- The grid remains in the world plane (`XY`/`XZ` as currently implemented)
  - this keeps the workspace visually stable while the imported object turns
- Added persistent display rotation state:
  - `_model_yaw_deg`
  - `_model_pitch_deg`
- Added model display transform helpers:
  - `_apply_model_display_transform()`
  - `_reset_model_display_rotation()`
  - `_orbit_model_by_delta(...)`
- Reset/load flows now clear display rotation before fitting camera:
  - `clear_view()`
  - `set_mesh(...)`
  - `reset_camera()`
- **Raycast picking / hover compensation**
  - `_raycast_face()` inverse-transforms the screen ray into model space when the display is rotated
  - preserves face picking and hover on the rotated-on-screen object

Result:

- Imported object turns/moves visually during orbit
- Grid stays fixed and no longer appears to rotate with the model
- Hover/select picking continues to work after turning the model

### 3. Qt Stylesheet Application + Primary Button Object Name

Implemented in:

- `ui/theme/apply_theme.py`
  - Appends a **global QSS override block** derived from `dev/specs/ui-enhance-v2.md`
  - Cross-referenced `dev/specs/ui-enhance.md` viewport `QOpenGLWidget` styling logic
- `qt_app/ribbon_window.py`
  - Run Flatten button object name changed from `primaryAction` to `btnRunFlatten`
- `ui/icon_loader.py`
  - Keeps accent icon tint behavior for both object names:
    - `primaryAction`
    - `btnRunFlatten`
- `qt_app/viewport.py`
  - Removed local viewport style rules that were overriding the global `QOpenGLWidget` border/background styles

Result:

- Global dark industrial QSS override is active
- `QToolButton#btnRunFlatten` accent styling now applies to **Run Flatten**
- Primary button icon remains readable (uses `ON_ACCENT` tint)

### 4. Phase 3 (Industrial Polish) - Ribbon / HUD / Wireframe Pass

Implemented in:

- `qt_app/ribbon_window.py`
- `qt_app/viewport.py`
- `ui/icon_loader.py`
- `ui/icons/svg_icon.py`
- `ui/icons/phase3_b64_icons.py`

Changes:

- Added inline Base64 SVG icon support
  - `ui/icon_loader.py` now supports applying icons from Base64 SVG strings
  - `ui/icons/svg_icon.py` now supports rendering SVG content directly from text (not only file paths)
- Added Phase 3 icons (consistent stroke width = `2`)
  - `ICON_ORBIT_3D_SVG_B64`
  - `ICON_IMPORT_3D_SVG_B64`
- Ribbon hierarchy refactor for **SETUP** and **FLATTEN**
  - Primary actions use large `QToolButton` layout (icon above text)
  - Secondary tools grouped into compact framed grids (2x2 / compact clusters)
  - Added a large **Run Flatten** action button inside the Flatten tab (`#btnRunFlatten`)
  - Added token-based `QToolButton` hover/pressed styling directly on the refactored ribbon controls
- Splitter polish
  - 3D/2D `QSplitter` handle reduced to `4px` and themed with border/accent hover
- Viewport HUD polish
  - Semi-transparent dark HUD panel with tighter spacing/padding
  - Standardized icon semantics (Orbit uses circular-arrows icon instead of ambiguous hand/glyph)
  - Floating orbit button now uses the new Base64 Orbit icon and matching hover/pressed styling
- Adaptive wireframe rendering / grid readability
  - Wireframe line width adapts to viewport theme:
    - dark = `2.5`
    - light = `1.2`
  - Existing polygon offset fill pass remains active (`glEnable(GL_POLYGON_OFFSET_FILL)` + `glPolygonOffset(1.0, 1.0)`)
  - Light-theme grid major/minor contrast strengthened for better visibility against `VP_BG`

Result:

- Ribbon hierarchy is closer to a CAD workflow (clear primary vs secondary actions)
- Orbit controls read more clearly and feel less "UI-mismatched"
- Wireframe visibility is improved in dark mode and grid lines are easier to read in light mode

### 4b. Phase 3 Cleanup Finalization (Singleton Ribbon + Ghost Orbit HUD)

Follow-up cleanup (after screenshot review + `dev/specs/ui-cleanup-final.md`) corrected several Phase 3 regressions:

- Removed duplicated **Import** / **Run Flatten** actions from the top toolbar
  - these actions now exist only once in the ribbon tabs
- Refined ribbon button hierarchy
  - **Import 3D** and **Run Flatten** remain the only large action buttons
  - secondary Setup / Flatten tools were converted to compact icon-only `QToolButton`s with tooltips (historical state; later reversed in `4e`)
- Ensured **Run Flatten** is the only solid cyan (`#00AEEF`) primary action button
- Orbit HUD cleanup
  - orbit HUD button now uses a "ghost" style (transparent, borderless, centered icon)
  - orbit icons (HUD + floating orbit drag button) increased to `32x32` inside `48x48` buttons for proper centering (final hard-refactor sizing)
  - HUD container moved to bottom-right with `10px` margin
- Wireframe cleanup
  - explicit per-frame wireframe width policy now enforces:
    - dark = `2.5`
    - light = `1.2`
  - `GL_DEPTH_TEST` is explicitly enabled in the mesh item paint path before draw passes

### 4c. Hard Refactor Finalization (Ribbon Consolidation + Icon Registry)

Follow-up hard refactor (after `dev/specs/ui-refactor-final.md`) replaced the ad-hoc Phase 3 ribbon/HUD layout code with a consolidated implementation.

Implemented in:

- `qt_app/ribbon_window.py`
- `qt_app/viewport.py`
- `ui/icon_loader.py`
- `ui/icons/phase3_b64_icons.py`

Changes:

- Ribbon rebuilt around a single helper:
  - `create_ribbon_button(type="large"/"small", ...)`
  - ensures consistent sizing, style, icon assignment, and tooltips
- Ribbon singleton rule enforced:
  - **Import** and **Run Flatten** no longer exist in the top toolbar
  - top toolbar now contains utility actions (2D preview / export / settings / about)
- Primary action hierarchy enforced:
  - only **Import** and **Run Flatten** are large `ToolButtonTextUnderIcon` buttons
  - **Run Flatten** is the only cyan-accent button (`#00AEEF`)
- Setup secondary controls simplified to compact icon-only buttons (historical `4c` state; later reversed in `4e`):
  - `Reset View`
  - `Wireframe`
  - `Grid` (new functional toggle wired to `ThreeDViewportWidget.set_grid_visible(...)`)
- HUD refactor:
  - transparent `HUDContainer` with horizontal layout
  - orbit button object name standardized to `hudOrbitButton`
  - forced sizing for centering:
    - button = `48x48`
    - icon = `32x32`
  - bottom-right anchoring remains `10px`
- Icon access refactor:
  - `IconRegistry.get_icon("orbit")`
  - `IconRegistry.get_icon("import_3d")`
  - UI files no longer reference Base64 constants directly

Result:

- Ribbon is visually cleaner and structurally consistent
- Duplicate primary actions are removed
- Orbit HUD icon alignment is fixed and predictable across DPI scales
- Base64 icon assets are centralized behind a named registry API

### 4d. Hard Refactor Recovery / Corrective Pass (Ribbon + HUD + Pivot Lock)

Follow-up corrective work (after UI regression review) was applied directly to restore usability and professional CAD semantics.

Implemented in:

- `qt_app/ribbon_window.py`
- `qt_app/viewport.py`

Changes in `qt_app/ribbon_window.py`:

- Enforced ribbon rebuild safety:
  - `_build_ribbon()` now clears/deletes an existing ribbon instance before rebuilding to avoid duplicate widgets when the UI is reconstructed
- Kept the singleton primary-action rule:
  - **Import 3D** and **Run Flatten** remain ribbon-only primary actions
  - top toolbar remains utility-focused (2D preview / export / settings / about)
- Preserved and reasserted primary button semantics:
  - **Import 3D** and **Run Flatten** are explicit `ToolButtonTextUnderIcon`
  - **Run Flatten** keeps `setObjectName("btnRunFlatten")` for cyan accent styling
- Removed layout-loop ambiguity in ribbon groups:
  - secondary controls are now added explicitly (single pass) instead of grouped append loops that were contributing to regressions during refactor churn
- Added/kept functional grid toggle in the Setup ribbon:
  - `Grid` button is wired to `ThreeDViewportWidget.set_grid_visible(...)`
- Switched icon assignment in ribbon/top-toolbar code to `IconRegistry.get_icon(...)`
  - avoids direct icon helper usage in layout code and keeps icon sourcing centralized

Changes in `qt_app/viewport.py`:

- HUD rebuilt as a transparent bottom-right overlay:
  - `HUDContainer` uses a transparent background and horizontal layout
  - bottom-right anchor margin is `10px`
- Orbit HUD button cleanup:
  - `hudOrbitButton` is transparent / borderless ("ghost" style)
  - forced sizing for centering:
    - button = `48x48`
    - icon = `32x32`
- Floating orbit drag button cleanup:
  - transparent / borderless styling
  - forced sizing:
    - button = `48x48`
    - icon = `32x32`
- HUD icon usage moved to `IconRegistry.get_icon(...)`
  - no inline SVG generation in viewport layout code
- Hidden HUD pan/zoom override toggles (kept for compatibility)
  - the toggle objects still exist for the current methods/signals
  - they are no longer shown in the visible HUD to avoid ambiguous iconography
- Camera pivot lock reinforcement:
  - `mouseDoubleClickEvent()` no longer recenters the camera to a picked-face centroid
  - `_frame_selected_region()` now keeps the camera pivot at the **model bounding-box center** and only adjusts distance/framing
- Wireframe / render-pass visibility safeguards:
  - `_CadMeshItem.paint()` explicitly enables `GL_DEPTH_TEST`
  - `paintGL()` reasserts per-frame wire width policy (`dark=2.5`, `light=1.2`)
  - `paintGL()` reasserts polygon offset fill on the face mesh item when needed

Result:

- Ribbon and HUD regressions from the derailed refactor were corrected without reintroducing duplicated primary actions
- Orbit pivot behavior is now consistently locked to the model bounding-box center during normal operation and frame-selection actions
- Wireframe visibility/readability is more stable in dark mode

### 4e. Ribbon Label Restoration (Post-Refactor UX Follow-up)

User feedback after the hard refactor noted that the ribbon became too icon-heavy and lost semantic clarity compared to earlier usable builds.

Implemented in:

- `qt_app/ribbon_window.py`

Changes:

- Restored visible labels on secondary ribbon buttons (current state)
  - secondary ribbon buttons now use `ToolButtonTextBesideIcon` instead of icon-only presentation
  - examples: `Reset Camera`, `Wireframe`, `Grid`, `Smart Select`, `Single Pick`, `Clear`, `Invert`, `Isolate`, `Technical`, `Edges`
- Increased ribbon strip height to support visible labels without clipping
  - `_phase3_ribbon_strip_height` increased to `108` to preserve text-under-icon readability for primary buttons and text visibility in grouped controls
- Restored visible labels on top-right utility buttons
  - `Settings`
  - `About`
- Improved top-toolbar 2D preview wording
  - button label now toggles between:
    - `Show 2D Preview`
    - `Hide 2D Preview`

Current ribbon semantics (superseding the icon-only note in `4b`/`4c`):

- Primary ribbon actions:
  - large `ToolButtonTextUnderIcon`
  - `Import 3D`, `Run Flatten`
- Secondary ribbon actions:
  - labeled `ToolButtonTextBesideIcon` with icons (not icon-only)
  - still keep tooltips for discoverability

Follow-up note for future agents:

- If the ribbon becomes crowded again (especially at 125-150% DPI), prefer:
  - shortening labels (e.g., `Reset Cam`)
  - grouping less-used actions into overflow/menu buttons
  - or using a true 2-row compact grid only for advanced/rare actions
  - avoid reverting all secondary actions to icon-only unless usability is revalidated with screenshots/runtime testing

### 5. PHASE 2 Visual Parity Mode (Unified Command Bar Recovery)

This phase replaces the old ribbon/tab workflow with a single always-visible command surface.

Implemented in:

- `qt_app/unified_command_bar.py`
- `qt_app/ribbon_window.py`
- `ui/theme/industrial_cad.qss`

Changes:

- Added `UnifiedCommandBar(QWidget)` with grouped cards:
  - `VIEW`
  - `SELECT`
  - `FLATTEN`
  - `OUTPUT`
- All command bar action controls are **icon + label** `QPushButton` widgets
  - no icon-only command buttons in the unified bar
- Object names added for QSS styling:
  - `CommandBar`
  - `GroupCard`
  - `GroupTitle`
  - `PrimaryButton`
  - `SecondaryButton`
  - `StandardButton`
  - `ToggleButton`
  - `Field`
- Industrial icon set integration by filename (`ui/icons/Industrial_SVG_Set_v1`)
  - `UnifiedCommandBar` loads icons using the phase2 `icon_map` filenames
  - `orbit.svg` (32x32 viewBox) is explicitly preloaded at 32px for render-path validation
- Active UI build path changed in `RibbonMainWindow._build_ui()`:
  - inserts **one** `UnifiedCommandBar` at the top of the central layout
  - removes the tab ribbon from the active layout path
  - no active top-toolbar construction path
- Existing UI handlers preserved via compatibility aliases in `RibbonMainWindow`
  - unified-bar controls are mapped to historical attribute names (e.g. `toggle_2d_btn`, `export_btn_top`, `run_flatten_btn_tab`, etc.)
  - allowed signal wiring to reuse existing methods without algorithm changes
- PH2 callback wiring (`UI-only`) added
  - import/reset/wireframe/grid/select/2D-preview/flatten/nest/export/settings/about wired to existing handlers
  - no flatten, nesting, DXF, or shader logic changes
- Theme styling (tokenized QSS) added for unified command bar
  - `Run Flatten` is the `PrimaryButton` (accent CTA)
  - `Export DXF` is the `SecondaryButton` (emphasized but less dominant)
  - command-bar spacing/button heights follow the 8px-grid spec direction
- Legacy duplicate UI builders disabled (cleanup)
  - `_build_top_toolbar()` stubbed/disabled in PH2 mode
  - `_build_ribbon()` stubbed/disabled in PH2 mode

Result:

- No `Setup / Flatten / Production` tab switching in the active UI path
- One unified command bar is the primary command surface
- Duplicate top-right controls are removed from the active layout path
- Command discoverability is improved because all command bar controls are labeled

#### 5a. How PHASE 2 Was Executed (Strict Step-Gated Recovery)

PHASE 2 was implemented as a **strict, step-by-step refactor** (UI-only) with small commits and explicit completion checks after each step.

Execution model used:

- Source of truth:
  - `UI-status.md`
  - `Industrial_CAD_Theme_v1.md`
  - `UI_Refinement_Phase_1.md`
  - `dev/specs/UI-recovery-plan.md`
  - `ui/icons/Industrial_SVG_Set_v1/README.md`
- Step gating:
  - `PH2-S1` through `PH2-S5` executed in order
  - each step was validated before moving on
  - one commit per step (plus a pre-PH2 checkpoint)
- Scope control:
  - UI layout / widget wiring / QSS only
  - no flattening, nesting, DXF export, or viewport shader pipeline changes in PHASE 2

Implementation method (important for future cleanup):

- `PH2-S1` created `qt_app/unified_command_bar.py` as a **new isolated widget**
  - intentionally added first without removing the old ribbon path
  - reduced risk while the widget structure, object names, and icon loading were being stabilized
- `PH2-S2` switched the active build path in `RibbonMainWindow._build_ui()`
  - inserted the unified bar into the main layout
  - stopped adding the top toolbar and tabbed ribbon in the active path
  - introduced compatibility aliases (mapping new controls to legacy attribute names) so existing methods could keep working
- `PH2-S3` added signal wiring in a dedicated helper (`_wire_unified_command_bar_actions()`)
  - connected unified bar controls to existing handlers
  - explicitly reused old callbacks instead of rewriting business logic
- `PH2-S4` added tokenized QSS styling in `ui/theme/industrial_cad.qss`
  - used PHASE 2 object names (`CommandBar`, `GroupCard`, `PrimaryButton`, etc.)
  - made `Run Flatten` primary and `Export DXF` secondary
- `PH2-S5` cleanup/audit
  - disabled legacy `_build_top_toolbar()` and `_build_ribbon()` code paths with stubs (rather than deleting immediately)
  - updated this status file with PHASE 2 details

Why compatibility aliases were used:

- `RibbonMainWindow` already had many methods expecting attributes like:
  - `toggle_2d_btn`
  - `run_flatten_btn_tab`
  - `export_btn_top`
  - `settings_btn_top`
- Rebinding unified-bar controls to these names allowed a lower-risk UI refactor without touching non-UI logic.
- This is intentional technical debt for PHASE 2 and should be cleaned once the unified bar layout stabilizes.

#### 5b. PHASE 2 Commit Sequence (Exact)

Pre-checkpoint before strict PHASE 2 work:

- `790ee44` `chore: checkpoint pre-phase2 ui refactor state`

PHASE 2 step commits:

- `9d5888f` `PH2-S1: add unified command bar shell widget`
- `9fdc936` `PH2-S2: replace active ribbon path with unified command bar`
- `98507d2` `PH2-S3: wire unified command bar to existing UI handlers`
- `17f4d7c` `PH2-S4: style unified command bar with industrial theme tokens`
- `86cc32c` `PH2-S5: disable legacy ribbon paths and update UI status`

Branch note:

- The requested branch namespace was `ui/enhance`.
- Local work was performed on `ui-enhance` because this repo has a ref namespace conflict with an existing `ui` ref that blocks creating a local `ui/enhance` branch.
- Remote work previously targeted `3DXflat/ui/enhance`.

#### 5c. PHASE 2 Validation Method (What Was Actually Tested)

Because a working Qt runtime was not available in the execution environment during PHASE 2, completion checks were performed with a combination of:

- `py_compile` syntax checks
- static text/AST audits
- targeted code-path verification in `ribbon_window.py` and `unified_command_bar.py`

What the static PHASE 2 audits verified:

- `UnifiedCommandBar` is inserted in the active `_build_ui()` path
- active `_build_ui()` no longer calls `_build_top_toolbar()` / `_build_ribbon()`
- legacy builder methods exist but are neutralized (stubs/disabled paths)
- required signal connections exist for import/view/select/flatten/output/settings/about actions
- icon filenames referenced by `UnifiedCommandBar.ICON_MAP` exist in `ui/icons/Industrial_SVG_Set_v1`
- `UI-status.md` includes PHASE 2 documentation

What was not verified in-runtime during PHASE 2:

- actual widget rendering/alignment under `PySide6`
- DPI scaling behavior
- live button interaction in a running Qt app
- visual parity against screenshots beyond code-level intent

#### 5d. PHASE 2 Visual Parity Correction (Two-Row Command Surface Recovery)

After the first PHASE 2 unification pass, a follow-up strict recovery cycle was required because the UI still showed layout glitches and visual mismatch against the target mock:

- ghosted/clipped command groups
- grouped-card matrix look (instead of a single continuous command surface)
- inconsistent prominence for `Run Flatten` / `Export DXF`

This second PHASE 2 cycle kept the same UI-only boundary (no algorithm/render-pipeline changes) and focused on **containment + layout structure + CTA hierarchy**.

Files touched in the correction cycle:

- `qt_app/unified_command_bar.py`
- `qt_app/ribbon_window.py`
- `ui/theme/industrial_cad.qss`
- `UI-status.md`

What was changed (implementation detail):

1. Command bar containment/opacity hardening (`PH2-S1`)
   - `UnifiedCommandBar` explicitly forced into normal layout flow as a fixed-height block:
     - `QSizePolicy(Expanding, Fixed)`
     - `setFixedHeight(128)`
   - Enabled styled background painting and disabled translucency:
     - `WA_StyledBackground = True`
     - `WA_TranslucentBackground = False`
     - `setAutoFillBackground(True)`
   - Kept `RibbonMainWindow._build_ui()` layout order as:
     - command bar first
     - viewport splitter second (stretch=1)

2. Replaced group-card matrix with exact two-row command surface (`PH2-S2`)
   - `UnifiedCommandBar` no longer builds `VIEW/SELECT/FLATTEN/OUTPUT` card panels
   - Rebuilt as two explicit horizontal rows:
     - `Row1General`
     - `Row2Workflow`
   - Added thin `CommandSeparator` vertical lines and spacing instead of card containers
   - Preserved compatibility widgets needed by existing window logic (`selected_label`, `quality_gauge`, `seam_slider`, `seam_label`, `export_path_label`) as hidden controls

3. CTA prominence + label enforcement (`PH2-S3`)
   - `Run Flatten` now uses explicit object name:
     - `btnRunFlattenPrimary`
   - `Export DXF` now uses explicit object name:
     - `btnExportDxfSecondary`
   - `UnifiedCommandBar` icon loader now supports color override so primary CTA icons render with `ON_ACCENT` tint
   - `Show/Hide 2D Preview` label remains text-based and is updated by `RibbonMainWindow._set_2d_preview_visible(...)`

4. Row-based QSS styling (`PH2-S4`)
   - Replaced PH2 card-style QSS assumptions with row-based selectors:
     - `QFrame#Row1General`
     - `QFrame#Row2Workflow`
     - `QFrame#CommandSeparator`
   - Added CTA styles for:
     - `QPushButton#btnRunFlattenPrimary`
     - `QPushButton#btnExportDxfSecondary`
   - Kept all command-bar controls as icon + label (no icon-only command buttons)

Why the overlap/ghosting bug likely happened (root-cause analysis):

- The earlier unified bar implementation used a **group-card matrix** (multiple nested panels) inside a command-bar container while the visual target required a continuous two-row strip.
- The command bar background could also render inconsistently if Qt stylesheet background painting was not explicitly enabled on the widget (`WA_StyledBackground` / `setAutoFillBackground`).
- Combined with a mismatched visual structure (cards inside a strip), this produced the "ghosted/clipped panel" appearance even though the layout order in `RibbonMainWindow._build_ui()` was already correct.

Final structure (current PHASE 2 visual parity direction):

- `Row1General`:
  - `Import 3D`, `Reset View`, `Wireframe`, `Grid`
  - units / scale / mesh info
  - `Settings`, `About` (right side)
- `Row2Workflow`:
  - `Smart Select`, `Single Pick`, `Clear`, `Invert`, `Isolate`, `Show/Hide 2D Preview`
  - `Method` field, `Technical`, `Edges`
  - `Run Flatten`, `Nest`, `Export DXF`

Correction cycle commits (strict step-gated):

- `85d0598` `PH2-P0 checkpoint before visual parity fixes`
- `fa30367` `PH2-S1: fix command bar containment and opacity`
- `ce3c12c` `PH2-S2: refactor unified command bar into two rows`
- `26a7096` `PH2-S3: enforce CTA hierarchy and labeled actions`
- `20e14eb` `PH2-S4: style two-row command bar with theme tokens`
- `PH2-S5` (this documentation/wiring verification step; see latest commit after this update)

Known follow-up items (next phase):

- Runtime visual tuning still needed against screenshots (spacing balance, exact widths, DPI behavior)
- Hidden compatibility controls should be removed only after the two-row layout is stable and all callbacks are confirmed in runtime
- The PHASE 2 pixel spec has an internal height inconsistency (`row1 + row2 + padding + gap > total height`), so final runtime sizing should be validated visually rather than assuming all numbers can be satisfied simultaneously

#### 5e. PHASE 2 Visual Parity Mode (Header Zoning Follow-up)

Short changelog note:

- Added **two-row header zoning** in `RibbonMainWindow`:
  - `headerArea` (opaque container) with `row1SystemBar` + `row2CommandBar`
- Added **header bottom border separation** (`1px`) via QSS on `headerArea`
- Moved `Settings` / `About` into the thin system bar (Row1) to reduce command-row clutter
- Kept `UnifiedCommandBar` as the only workflow command surface in Row2 (no tabs / no second toolbar)
  - current PH2-VP target sizing uses a fixed `88px` row2 command strip with two internal `40px` lines
- Orbit HUD icon now loads from file path `ui/icons/Industrial_SVG_Set_v1/orbit.svg` (no Base64 path for HUD orbit)

### 6. Seam/Cut MVP (Seamfix Branch)

Implemented in:

- `qt_app/ribbon_window.py`
- `qt_app/viewport.py`
- `qt_app/mesh_cutting.py` (new)
- `qt_app/flatten_panel.py` (new)

Changes:

1. Selection-driven flatten behavior is now explicit in the Qt pipeline
   - If faces are selected, the flatten worker builds/uses the selected face submesh.
   - If no faces are selected, flatten still uses the full mesh path and preserves legacy open-patch fallback behavior.

2. Added Cut/Seam interaction mode + left PropertyManager-style panel
   - New row-2 control: `Cut/Seam` toggle (alongside `Smart Select` / `Single Pick`).
   - Seam action controls moved to a left panel (`FlattenPanelWidget`) instead of the crowded command row.
   - Left panel sections now include:
     - `Selezioni` (selected faces count),
     - `Bordo (Anchor)` (anchor field + set/auto buttons),
     - `Tagli di scarico` (cut list + remove/clear),
     - `Precisione` slider,
     - `Stato` + guidance text.
   - Command row keeps only mode-level controls (`Smart Select`, `Single Pick`, `Cut/Seam`, `Clear`, `Invert`, `Isolate`).

3. Added edge picking + seam visualization in `ThreeDViewportWidget`
   - New seam state signal: `seamStateChanged`.
   - In Cut/Seam mode, edge picking now follows SolidWorks-like behavior:
     - hover near candidate edge highlights it,
     - `Click` toggles relief cut,
     - `Shift+Click` sets anchor edge.
   - Candidate edge priority:
     - selected faces -> patch boundary edges,
     - no selected faces -> feature edges (dihedral threshold) with triangle-edge fallback.
   - Overlay rendering:
     - hovered edge = cyan
     - anchor edge = green line
     - cut edges = red lines
   - Overlay rendering gracefully degrades if GL line overlay objects are unavailable; seam state logic still updates.

4. Added topology cutting utility module
   - `qt_app/mesh_cutting.py` provides:
     - topology diagnostics (`open_edges`, non-manifold, components, boundary loops),
     - seam cutting via vertex-duplication fan splitting,
     - anchor-edge remapping helpers after vertex duplication.

5. Flatten worker now supports closed meshes with user-defined cuts
   - Closed patch + no cuts now raises a user-facing blocking error:
     - "Closed mesh/selection detected (no open boundary)..."
   - If cuts are present, mesh is cut before flatten solve.
   - Post-cut topology is checked; warnings are emitted for non-disk-like outcomes.
   - If no user selection and the mesh is closed, legacy auto-extract-open-patch fallback is retained.

6. Anchor edge is used for deterministic output orientation
   - After solve, UVs are rotated/translated so the anchor edge is horizontal near origin.
   - DXF/SVG output is re-exported with the aligned UV frame.

Current status / limitation observed in runtime:

- The PropertyManager-like panel and hover/click seam picking are in place.
- Remaining work is visual rhythm/polish (spacing, typography, and panel density tuning against reference screenshots).

### 7. B-Rep Import + CAD Face/Edge Semantics (B-rep Branch)

Implemented in:

- `qt_app/brep_import.py` (new)
- `qt_app/ribbon_window.py`
- `qt_app/viewport.py`
- `qt_app/edge_selection.py`
- `requirements-optional-brep.txt` (new)
- `BREP_PLAN.md` (new architecture plan)

What was added:

1. Optional OpenCascade dependency path
   - New optional dependency file: `requirements-optional-brep.txt` with `pythonocc-core`.
   - STEP/IGES import is now capability-gated:
     - if OCC is missing, UI shows a clear message and does not crash.
   - Import filters now include:
     - `*.step *.stp *.iges *.igs` (plus STL/OBJ).

2. Native B-Rep loader with topology mappings
   - `load_brep(path)` now reads STEP/IGES via OpenCascade readers.
   - Tessellation uses `BRepMesh_IncrementalMesh`.
   - Output includes:
     - global triangle mesh (`tri_mesh_vertices`, `tri_mesh_faces`),
     - `tri_face_id` mapping triangle -> CAD face index,
     - `edge_polylines`,
     - `face_boundary_edge_ids`,
     - B-Rep face/edge counts and bbox metadata.

3. Active model type support in UI pipeline
   - `RibbonMainWindow` now tracks `model_type` (`mesh` or `brep`) and loaded B-Rep metadata.
   - Worker load path returns a B-Rep payload including CAD topology metadata.
   - STL/OBJ flow is preserved.

4. CAD face selection semantics
   - In B-Rep mode, clicking a tessellated triangle selects its parent CAD face (`tri_face_id`) rather than a single triangle.
   - Selection count in the left panel now reflects CAD face count.
   - Invert/isolate/frame-selected logic was updated so B-Rep face IDs still map correctly to triangle indices for rendering.

5. SolidWorks-like boundary chain seam picking for B-Rep patches
   - For selected CAD faces, boundary B-Rep edges are derived from `face_boundary_edge_ids` (edges used by exactly one selected face).
   - Boundary edges are grouped into maximal chains (`edge_selection.build_edge_chains`).
   - Hover and click in Cut/Seam mode use screen-space chain picking:
     - `Shift+Click` sets anchor chain,
     - `Click` toggles relief cut chain.
   - Overlay rendering shows hovered/anchor/cut chains using B-Rep edge polylines.

6. Flatten integration (triangle pipeline preserved)
   - Flatten still consumes triangles only.
   - B-Rep chain selections are mapped to tessellated mesh edge cuts and fed into existing seam-cut flow.
   - Closed selected patches without effective cuts still raise blocking messages in flatten worker.

Current B-Rep limitation:

- B-Rep chain/edge -> mesh-edge mapping is now geometric and patch-boundary aware, but can still fail on very coarse tessellation or ambiguous near-parallel boundaries.
- If mapping still yields zero valid mesh edges for a selected Bordo/Taglio, flatten reports that cuts are outside the patch.
- UI currently shows representative edge labels in panel lists (not full chain names).

### 7.1 B-Rep Runtime Hardening Follow-up (B-rep)

Implemented follow-up stabilization after live runtime tests:

- `3DXFlat.bat`
  - Launcher now keeps app execution on the project/runtime venv interpreter and does not switch the whole app to micromamba Python.
  - OCC runtime is provisioned in a local micromamba env (`python=3.12` + `pythonocc-core`) using short Windows-safe prefixes (`%USERPROFILE%\3DXF\...`) to avoid long-path extraction/cache failures.
  - OCC overlay strategy changed from full `site-packages` sharing to OCC-only overlay copy:
    - source: `<mamba_env>\Lib\site-packages\OCC`
    - target: `%LOCALAPPDATA%\3DXFlat\occ-overlay\OCC`
  - OCC DLL path injection is now conditional:
    - first try OCC import with package overlay only,
    - only inject mamba DLL dirs into `PATH` if OCC import still fails.
    - This avoids OpenGL/Qt conflicts caused by global DLL path pollution.
  - Dependency sanity check no longer imports `customtkinter` (prevents false failure on Python builds without Tk).

- `flatten_surface/flatten_surface.py`
  - Removed top-level `tkinter` imports.
  - `tkinter` is now imported lazily only in interactive CLI file-picker flow (`main()` with missing `path_input`).
  - Qt path (`flatten_mesh`) no longer depends on Tk being installed.

- `main.py`
  - Tk fallback import now has explicit error handling.
  - If Qt fails and Tk is unavailable, the app reports a clear fallback failure instead of masking root cause.

- `qt_app/brep_import.py`
  - Added explicit OCC runtime preparation in-process:
    - honors `MAMBA_ENV_PREFIX` and `OCC_OVERLAY_SITE`,
    - adds candidate OCC DLL directories via `os.add_dll_directory(...)` on Windows.
  - OCC capability check is now strict and practical:
    - validates `OCC.Core.IFSelect`, `OCC.Core.STEPControl`, and `OCC.Core.IGESControl` imports (not just `import OCC.Core`).
  - Added pythonocc wrapper compatibility handling:
    - triangulation API variants (`Node/Triangle` vs `Nodes/Triangles`),
    - TopExp mapping symbols available in current wrappers.

Result of follow-up:

- Qt app startup no longer hard-fails due to missing `tkinter` import side-effects.
- STEP/IGES loader no longer fails at `_IFSelect` DLL load in configured OCC overlay runtime.
- OCC integration remains optional and does not force STL users onto OCC runtime.

Additional current CAD-data limitation observed:

- Some STEP files can be topologically edge-only in OCC for current reader/settings (example observed: `data/ProvaFunzioneTelo.STEP` => edges detected, zero faces).
- In that case loader correctly reports no B-Rep faces and import cannot proceed as face-based CAD patch workflow.

### 7.2 B-Rep Cut/Seam Selection Parity Update (SolidWorks-like Behavior)

Implemented follow-up UX and mapping changes on branch `B-rep`:

1. Click-vs-drag seam interaction (no Ctrl required for normal seam selection)
   - In `Cut/Seam` mode:
     - `Click` toggles relief cut.
     - `Shift+Click` sets anchor.
   - Left mouse uses an explicit click-vs-drag threshold (`8px`):
     - release without drag = seam/selection click action,
     - drag past threshold is forwarded to base viewport navigation path.

2. Edge-first B-Rep picking with optional chain mode
   - Left panel now exposes B-Rep seam pick granularity:
     - `Edge Mode (segmento)` (default)
     - `Chain Mode (tangente)`
   - Edge mode picks a single B-Rep boundary edge under cursor (hover -> click).
   - Chain mode picks the tangent-continuous chain containing the best hovered edge.
   - Chain construction now breaks at hard corners using tangent continuity checks (instead of maximal loop-only grouping).

3. Advanced mesh-edge seam mode
   - New left panel option:
     - `Advanced mesh seam (Ctrl+Click)`
   - When enabled in `Cut/Seam` mode:
     - `Ctrl+Click` toggles tessellated patch boundary mesh edges directly,
     - `Shift+Ctrl+Click` sets anchor on a tessellated mesh edge.
   - This bypasses B-Rep chain semantics for manual segmented seams.

4. Robust B-Rep edge -> tessellated mesh mapping
   - Replaced nearest-vertex heuristic mapping with a geometric edge mapper in `qt_app/mesh_cutting.py`.
   - Mapping now:
     - builds candidate mesh edges from selected patch boundary first,
     - scores candidates by spatial proximity + directional consistency against B-Rep polyline segments,
     - keeps the largest connected mapped edge subset to avoid scattered edges.
   - `qt_app/viewport.py` now rebuilds this mapping per selected CAD patch boundary during seam candidate recomputation.

5. Regression test added
   - `tests/test_edge_selection.py` now includes tangent-segmentation coverage:
     - collinear edges stay chained,
     - right-angle corners split into independent selectable segments.

### 7.3 B-Rep Selection Persistence + Advanced Seam Routing Fix

Implemented follow-up fixes on branch `B-rep-selection-persistence`:

1. Camera/view navigation preserves selection + seam state
   - View cube / view preset / reset-camera navigation is now guarded as camera-only:
     - selected CAD faces persist,
     - anchor edge persists,
     - relief cut edges persist,
     - seam candidate cache persists.
   - Added explicit seam-state snapshot/restore around camera preset/reset navigation paths.

2. Advanced mesh seam now works with selected CAD faces
   - In `Cut/Seam` mode with `Advanced mesh seam` enabled:
     - `Ctrl+Click` always targets tessellated patch boundary edges,
     - `Shift+Ctrl+Click` sets anchor on tessellated patch boundary edge.
   - Works with selected B-Rep faces still active (no deselection required).
   - Added persistent manual B-Rep mesh-edge seam state so advanced cuts are not dropped by B-Rep chain sync.

2b. Empty-patch persistence rule
   - If B-Rep face selection becomes empty, existing seam anchor/cuts are now preserved and shown as:
     - `Patch: inactive (no patch)`
   - Seam data is no longer auto-cleared on empty selection; only incompatible edges are pruned when a new patch is selected.

3. Seam candidate recompute strategy is now dirty-flag based
   - Recompute is triggered by:
     - selection changes,
     - model load/change,
     - pick mode changes,
     - precision slider changes.
   - Recompute is not triggered by:
     - orbit/pan/zoom,
     - view presets,
     - view cube clicks.

4. Debug instrumentation (env-gated)
   - Added `DXF_DEBUG_SELECTION=1` instrumentation for:
     - reset callsites (`clear_view`, `set_mesh`, `reset_camera`, `apply_view_preset`, selection/cut clear helpers),
     - seam-candidate recompute state transitions,
     - Cut/Seam Ctrl+Click branch routing details.
   - Default runtime remains silent when env var is not set.

Manual acceptance checks performed:

- Load `data/new iges test/ProvaFunzioneTelo.IGS`.
- Select patch CAD faces and keep `Facce selezionate > 0`.
- Enable `Advanced mesh seam`, then use `Ctrl+Click` to toggle multiple tessellated boundary edges.
- Use `Shift+Ctrl+Click` to set anchor.
- Switch view repeatedly via view cube/presets (`TOP/FRONT/RIGHT`) and verify faces, anchor, cut list remain intact.

## How the 3D Viewport Currently Works

`ThreeDViewportWidget` (`qt_app/viewport.py`) extends `pyqtgraph.opengl.GLViewWidget` and manages:

- Camera navigation:
  - orbit / pan / zoom (mouse + HUD buttons)
  - current default orbit uses a **turntable model-rotation path** (mesh rotates, world grid stays fixed)
  - grid visibility is now also controllable from the PHASE 2 unified command bar (`Grid` toggle)
  - visible HUD controls are currently: **Fit**, **Orbit**, **Toggle 2D Preview**
  - pan/zoom override toggle objects still exist in code but are hidden from the visible HUD (compatibility holdover)
- Mesh rendering:
  - face mesh item
  - wireframe/edge mesh item
  - selection overlay mesh item
- Selection:
  - raycast picking against triangles
  - raycast is compensated for display rotation when turntable mode is active
  - smart selection via face adjacency + angle threshold
- Camera target / orbit center:
  - pyqtgraph uses `self.opts["center"]` as orbit pivot
  - camera position is derived from `center + distance + rotation`
  - current corrective pass keeps the pivot locked to the **model bounding-box center**
    - double-click no longer re-centers to a picked face
    - frame-selected-region now preserves bbox-center pivot and adjusts distance only

Key rendering flow:

1. `paintGL()` prepares pipeline state
   - applies adaptive wireframe width policy (`2.5` dark / `1.2` light)
   - reasserts face polygon-offset fill when needed for wireframe readability
2. `paintGL()` updates headlight shader uniforms from current camera/view matrix
3. pyqtgraph draws mesh items
4. HUD / floating orbit UI updates

## Known Bugs / Risks / Limitations (Current)

1. `dev/specs/ui-enhance-v2.md` formatting is malformed/escaped.
   - The file mixes escaped markdown and QSS text inside a code block after the wireframe snippet.
   - The intent was implemented, but future agents should treat it as a spec, not executable code.

2. OpenGL line width support is driver-dependent in Core Profile.
   - The viewport now requests adaptive widths (`2.5` dark / `1.2` light), but many modern GPU drivers still clamp line width to `1.0`.
   - If wireframes are still too thin, a shader-based edge overlay or duplicated line geometry may be needed.

3. Headlight implementation is pyqtgraph-specific (not fixed-function lighting).
   - This repo uses pyqtgraph GLSL mesh shaders, so the C++ `glLightfv` legacy path is not the active rendering path.
   - The implemented solution uses a custom GLSL shader and per-frame uniform updates.

4. Viewport background color is controlled by both QSS and OpenGL clear color.
   - QSS affects widget frame/border and some background presentation.
   - Actual 3D canvas clear color still comes from `setBackgroundColor(...)` / `glClearColor(...)`.

5. Framing selected region still changes distance (but not pivot).
   - The current corrective pass keeps the orbit pivot at the model bounding-box center during `_frame_selected_region()`.
   - Framing still changes camera distance based on the selected-region bounds, which is intentional.

6. The gradient/vignette is currently a post-paint overlay.
   - It improves visual depth, but it is not a true OpenGL background gradient pass yet.
   - A future shader/fullscreen-pass implementation would be cleaner and more controllable.

7. Camera telemetry/UI signals may not fully represent turntable display rotation.
   - Orbit drag now rotates the model display items (not only the camera).
   - Any UI elements that infer orientation only from camera azimuth/elevation may not reflect the object's turned orientation without an additional model-rotation signal.

8. Base64 SVG icons remain a stopgap, even though access is centralized.
   - UI code now uses `IconRegistry` for ribbon/HUD icon lookup (no inline SVG strings in layout code).
   - A future cleanup can still move the icon set to compiled Qt resources if the icon library grows.

9. Ribbon label density may need another pass at high DPI / narrow widths.
   - Secondary ribbon controls are intentionally labeled again (text + icon) for usability.
   - At 125-150% DPI, some groups may require shorter labels or overflow grouping to avoid crowding.

10. PHASE 2 uses compatibility aliases in `RibbonMainWindow`.
   - Unified command bar controls are assigned to legacy attribute names to minimize risk.
   - A future cleanup can remove more legacy naming once the unified bar stabilizes.

11. PHASE 2 visual parity is structurally correct, but a follow-up polish pass is still expected.
   - The command bar is unified and labeled, but spacing, balance, and final CAD-grade visual rhythm may still need screenshot-driven tuning.
   - Future work should focus on alignment/visual polish before removing compatibility shims.

12. Legacy UI builders are stubbed, not deleted.
   - `_build_top_toolbar()` and `_build_ribbon()` are intentionally disabled in-place.
   - This preserves rollback/debug context, but it increases file size and can confuse future maintenance until a cleanup pass removes dead code entirely.

13. PHASE 2 testing was static due environment limitations.
   - A working `PySide6` runtime was not available in the execution environment when PHASE 2 was implemented.
   - Runtime UI regressions (layout clipping, size-policy issues, DPI alignment) must still be validated manually in the application.

14. PHASE 2 visual parity correction uses hidden compatibility widgets.
   - Some controls (e.g., seam slider / quality gauge / export-path label) remain instantiated but hidden to preserve legacy callback/state paths.
   - This is deliberate during stabilization and should be cleaned once runtime behavior is confirmed.

15. Seam/Cut workflow is split across row mode controls + left panel controls.
   - This is intentional (mode on row, actions in panel), but still needs screenshot-driven spacing/section hierarchy polish to look closer to SolidWorks PropertyManager.

16. Edge candidate rules are heuristic when no faces are selected.
   - Feature-edge based picking uses a fixed dihedral threshold and falls back to triangle-edge picking for heavy candidate sets.
   - This is robust, but complex meshes may still require user face selection for best predictability.

## Validation Performed

- Latest follow-up pass syntax checks:
  - `python -m py_compile qt_app/ribbon_window.py`
  - `python -m py_compile qt_app/viewport.py`
  - `python -m py_compile qt_app/mesh_cutting.py`
  - `python -m py_compile qt_app/flatten_panel.py`
  - `python -m py_compile qt_app/edge_selection.py`
  - `python -m py_compile tests/test_edge_selection.py`
  - `python -m pytest tests/test_edge_selection.py -q` (not executable in this environment: `pytest` missing)
- B-rep runtime hardening checks:
  - `python -m py_compile qt_app/brep_import.py`
  - `python -m py_compile flatten_surface/flatten_surface.py`
  - `python -m py_compile main.py`
  - venv + OCC overlay import check:
    - `import numpy, OCC.Core, pyqtgraph, OpenGL`
  - B-Rep load smoke check in runtime overlay:
    - `load_brep("data/test Amila.STEP")` succeeded
- PHASE 2 step-gate syntax checks:
  - `python -m py_compile qt_app/unified_command_bar.py`
  - `python -m py_compile qt_app/ribbon_window.py`
- PHASE 2 static audits (AST/text; no Qt import required):
  - verified active `_build_ui()` contains one unified command bar and no active ribbon/top-toolbar calls
  - verified legacy builder methods are stubbed/disabled
  - verified required unified-bar signal connections are present
  - verified `UnifiedCommandBar.ICON_MAP` files exist under `ui/icons/Industrial_SVG_Set_v1`
  - verified `UI-status.md` contains the PHASE 2 recovery section
- PHASE 2 visual parity correction static audits:
  - verified `UnifiedCommandBar` uses explicit `Row1General` / `Row2Workflow` rows (no `GroupCard` matrix in current implementation)
  - verified `Run Flatten` / `Export DXF` CTA object names (`btnRunFlattenPrimary`, `btnExportDxfSecondary`)
  - verified 2D Preview label toggle path still updates `Show/Hide 2D Preview`
- Python syntax checks passed:
  - `qt_app/viewport.py`
  - `qt_app/ribbon_window.py`
  - `ui/theme/apply_theme.py`
  - `ui/icon_loader.py`
  - `ui/icons/svg_icon.py`
  - `ui/icons/phase3_b64_icons.py`
- Runtime validation limitation during PHASE 2:
  - system `python` did not have `PySide6`
  - the project `.venv` Python launcher was not usable in this environment
  - therefore PHASE 2 completion tests were performed as static code audits instead of live UI interaction tests
  - runtime screenshots requested for visual parity were not generated in this environment for the same reason

## Recommended Next Checks (Manual Runtime)

1. Load an off-origin STL/OBJ and verify orbit pivot is centered on the mesh bounding box.
2. Rotate model 180 degrees and confirm face shading remains visible.
3. Toggle wireframe / edges and confirm line thickness and z-fighting behavior.
4. Confirm unified command bar **Run Flatten** button uses the primary accent styling and the icon remains visible.
5. Orbit the model and confirm the grid remains fixed while the object turns.
6. Hover/select faces after orbiting and confirm picking still matches the displayed rotated mesh.
7. Verify unified command bar layout renders correctly at normal DPI and 125%-150% Windows scaling (group spacing, button alignment, icon centering, and label clipping).
8. Verify all unified command bar actions keep visible text labels (semantic names) and do not regress to icon-only.
9. Double-click a face and confirm the orbit pivot does **not** jump to the picked face centroid.
10. Press `Z` / frame selected region and confirm distance changes while orbit pivot remains at bbox center.
11. Verify dark-mode wireframe line thickness increases to 2.5 and remains visible during rotation.
12. Verify no `Setup / Flatten / Production` tabs are visible and only one unified command bar is present.
13. Verify every command bar action is icon + label (no icon-only commands).
14. Verify `Run Flatten` is the primary CTA and `Export DXF` is secondary in the unified bar.
15. Verify the command bar is a solid opaque block (no ghosted/clipped group panels) and the viewport begins directly below it.
16. Verify the command surface is exactly two visible rows (General / Workflow) with no card-grid layout.
