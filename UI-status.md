# UI Status (Current)

## Scope / Context

This repository's UI is **Python**, not C++:

- **Qt bindings:** `PySide6`
- **3D viewport:** `pyqtgraph.opengl.GLViewWidget` (OpenGL-backed)
- **2D preview / nesting canvas:** `QGraphicsView` / `QGraphicsScene`
- **Styling:** global Qt stylesheet (QSS) via `ui/theme/apply_theme.py` + `ui/theme/industrial_cad.qss`

The recent work maps the `ui-enhance-v2.md` C++ `QOpenGLWidget` instructions to the equivalent Python/pyqtgraph implementation.

## Main UI Files (Current)

- `qt_app/ribbon_window.py`
  - Main ribbon-style window shell (top toolbar + tabs + viewport + side panels)
  - Creates the **Run Flatten** top action button
- `qt_app/viewport.py`
  - `ThreeDViewportWidget` (3D OpenGL viewport)
  - Mesh load/update, camera orbit/pan/zoom, selection, wireframe/edge rendering
- `ui/theme/apply_theme.py`
  - Builds and applies global app palette + global QSS
- `ui/theme/industrial_cad.qss`
  - Base tokenized theme stylesheet
- `ui/icon_loader.py`
  - Applies icon colors (including primary action button icon tint)

## What Was Changed (This Pass)

This file was updated again after an additional **Phase 1 viewport pass** (navigation + shading readability) on branch `ui-enhance`.

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
- Added **double-click pivot** behavior
  - double-clicking a visible face sets the orbit pivot to that face centroid (pick-point pivot)
- Added a **subtle gradient + vignette viewport overlay**
  - improves depth perception and silhouette separation in dark mode
- Upgraded the custom headlight shader to a **two-tone CAD-style readable shader**
  - hemisphere ambient + rim highlight + specular
- Fixed an important regression: `_update_mesh_visuals()` was resetting the mesh shader back to `"shaded"` on every refresh
  - this prevented the custom headlight shader from taking effect consistently

Result:

- Orbit feels more stable and CAD-like
- Pick-point orbit pivot is now available (double-click)
- Mesh remains more readable in dark mode and under rotation

### 3. Qt Stylesheet Application + Primary Button Object Name

Implemented in:

- `ui/theme/apply_theme.py`
  - Appends a **global QSS override block** derived from `ui-enhance-v2.md`
  - Cross-referenced `ui-enhance.md` viewport `QOpenGLWidget` styling logic
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

## How the 3D Viewport Currently Works

`ThreeDViewportWidget` (`qt_app/viewport.py`) extends `pyqtgraph.opengl.GLViewWidget` and manages:

- Camera navigation:
  - orbit / pan / zoom (mouse + HUD buttons)
- Mesh rendering:
  - face mesh item
  - wireframe/edge mesh item
  - selection overlay mesh item
- Selection:
  - raycast picking against triangles
  - smart selection via face adjacency + angle threshold
- Camera target / orbit center:
  - pyqtgraph uses `self.opts["center"]` as orbit pivot
  - camera position is derived from `center + distance + rotation`

Key rendering flow:

1. `paintGL()` prepares pipeline state
2. `paintGL()` updates headlight shader uniforms from current camera/view matrix
3. pyqtgraph draws mesh items
4. HUD / floating orbit UI updates

## Known Bugs / Risks / Limitations (Current)

1. `ui-enhance-v2.md` formatting is malformed/escaped.
   - The file mixes escaped markdown and QSS text inside a code block after the wireframe snippet.
   - The intent was implemented, but future agents should treat it as a spec, not executable code.

2. OpenGL line width support is driver-dependent in Core Profile.
   - `glLineWidth(2.0)` is requested and now set, but many modern GPU drivers clamp line width to `1.0`.
   - If wireframes are still too thin, a shader-based edge overlay or duplicated line geometry may be needed.

3. Headlight implementation is pyqtgraph-specific (not fixed-function lighting).
   - This repo uses pyqtgraph GLSL mesh shaders, so the C++ `glLightfv` legacy path is not the active rendering path.
   - The implemented solution uses a custom GLSL shader and per-frame uniform updates.

4. Viewport background color is controlled by both QSS and OpenGL clear color.
   - QSS affects widget frame/border and some background presentation.
   - Actual 3D canvas clear color still comes from `setBackgroundColor(...)` / `glClearColor(...)`.

5. Framing selected region can still change orbit target intentionally.
   - `ThreeDViewportWidget._frame_selected_region()` sets camera center to the framed region.
   - This is useful behavior, but it means the orbit pivot may temporarily move away from whole-model center after a frame-selection action.

6. The gradient/vignette is currently a post-paint overlay.
   - It improves visual depth, but it is not a true OpenGL background gradient pass yet.
   - A future shader/fullscreen-pass implementation would be cleaner and more controllable.

## Validation Performed

- Python syntax checks passed:
  - `qt_app/viewport.py`
  - `qt_app/ribbon_window.py`
  - `ui/theme/apply_theme.py`
  - `ui/icon_loader.py`

## Recommended Next Checks (Manual Runtime)

1. Load an off-origin STL/OBJ and verify orbit pivot is centered on the mesh.
2. Rotate model 180 degrees and confirm face shading remains visible.
3. Toggle wireframe / edges and confirm line thickness and z-fighting behavior.
4. Confirm top **Run Flatten** button uses the cyan accent (`#btnRunFlatten`) and the icon remains visible.
