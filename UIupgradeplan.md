# UIupgradeplan.md — 3DXFlat Advanced (Branding + Icons + Look & Feel)

**Goal:** Upgrade the app’s visual identity and UI consistency to a sellable, industrial-grade product called **3DXFlat Advanced** (not “Tent Maker”).

**Scope:** Branding system + icon system + theme + viewport look, with implementation steps Codex can execute.

**Non-goals:** Do not modify flattening algorithms in this plan (LSCM/ARAP correctness stays untouched). Focus on presentation and UX consistency.

---

## 0) Ground rules (do these first)

1. **Single source of truth for UI styling**
   - Create one theme module with tokens (colors, sizes, fonts, spacings).
   - No hardcoded colors in widgets.

2. **Assets must be embedded for distribution**
   - Use Qt Resource system (`.qrc`) so icons ship inside the app bundle.
   - Do not reference relative file paths from the working directory.

3. **SVG icon scaling**
   - Qt `QIcon` with SVG sometimes renders poorly on HiDPI if not handled correctly.
   - Use SVG as source but ensure correct size / pixmap generation for toolbuttons.
   - If needed, provide “baked” PNGs for critical toolbar sizes (24/32) as fallback.

---

## 1) Branding decisions (lock these in)

### Product name
- **3DXFlat Advanced**

### Tagline (pick one and use consistently)
- “Industrial Surface Unfolding Engine”
- “Precision 3D-to-2D Surface Flattening”

### Visual personality
- Industrial CAD dark UI
- Controlled accent color (no neon / gamer look)

### Primary accent color
- Engineering Blue: `#00AEEF`

---

## 2) Repository structure to add

Create a dedicated UI assets folder and theme package.

```
/ui
  /theme
    tokens.py
    apply_theme.py
  /assets
    /icons
      /svg
      /png (optional fallback)
    /brand
      logo.svg
      logo_mark.svg
      wordmark.svg
      app_icon.ico
      app_icon_256.png
  resources.qrc
```

Add a build step (later) to compile `resources.qrc` into Python resources (or load `.qrc` directly if your packaging supports it).

**Reference:** Qt resource system best practice for bundling assets.

---

## 3) Theme tokens (create `ui/theme/tokens.py`)

### Color tokens
Use these exact values initially (can be tuned later):

```text
BG_MAIN        #1F2227
BG_PANEL       #2A2F36
BG_HOVER       #323842
BORDER         #3A4048
TEXT_PRIMARY   #E5E9F0
TEXT_SECONDARY #9AA4B2
TEXT_DISABLED  #6B7480
ACCENT         #00AEEF
WARN           #F39C12
ERROR          #E74C3C
SUCCESS        #2ECC71
```

### Spacing tokens
```text
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
RADIUS_1 = 6
RADIUS_2 = 10
```

### Typography tokens
Prefer system-safe fonts first:

```text
FONT_FAMILY = "Segoe UI Variable"  (fallback: "Segoe UI", "Inter")
FONT_SIZE_RIBBON = 12
FONT_SIZE_BODY = 13
FONT_SIZE_TITLE = 16
FONT_WEIGHT_NORMAL = 400
FONT_WEIGHT_SEMIBOLD = 600
```

---

## 4) Apply theme globally (create `ui/theme/apply_theme.py`)

### Requirements
- Must apply to the whole app from `main.py` before creating windows.
- Must style:
  - QMainWindow, QDockWidget, QToolBar / ribbon widgets
  - QMenu, QMenuBar, QDialog
  - QComboBox, QLineEdit, QPushButton, QCheckBox, QRadioButton
  - QStatusBar

### Implementation approach
1. Set an application style (e.g., Fusion) for consistency.
2. Apply a Qt stylesheet built from tokens.
3. Ensure disabled states are legible.

---

## 5) Icon system

### Icon rules (must enforce)
- Base grid: **24×24**
- Stroke: **1.8px**
- Caps/joins: rounded
- No gradients, no shadows
- Prefer outline icons; only use fill for active/selected states

### Required icon list (v1)
Create these icons first, in one consistent family:

- `import_model`
- `surface_select`
- `isolate`
- `clear_selection`
- `invert_selection`
- `flatten`
- `pin_vertex`
- `strain_map`
- `export_dxf`
- `nest`
- `wireframe`
- `show_edges`
- `frame_selection`
- `settings`
- `about`

### Naming convention
- `ui/assets/icons/svg/<name>.svg`
- (optional) `ui/assets/icons/png/<name>_24.png`, `<name>_32.png`

### Qt loading rules
- Prefer SVG via `QIcon("qrc:/icons/svg/import_model.svg")`
- If SVG scaling issues appear on certain widgets, generate a pixmap at the exact requested size and set it.

Qt note: When adding multiple files to a `QIcon`, add SVG first to ensure correct icon engine selection. (Qt QIcon docs)

---

## 6) Brand assets

### Logo
Deliverables:
- `logo_mark.svg` (symbol only)
- `wordmark.svg` (text only)
- `logo.svg` (combined)

**Direction:** Mesh → Outline transformation mark.
- Left: small triangle mesh cluster
- Right: clean 2D polygon outline
- Mid: subtle dissolve / split

### Windows app icon
Deliverables:
- `app_icon.ico` containing multiple sizes in one ICO

Include at least these sizes (Windows guidance):
- 16×16, 24×24, 32×32, 48×48, 64×64, 256×256

(Windows recommends multiple images inside ICO for best scaling.)

---

## 7) Ribbon / workspace layout cleanup

### Objectives
- Reduce “prototype” feel.
- Consistent padding, alignment, icon sizes.
- Uniform button behavior.

### Rules
- Ribbon button icons: 24px
- Ribbon button padding: 8–12px
- Section titles: 12px semibold
- Avoid mixed icon sizes.

### Deliverable
- Update ribbon creation code to use:
  - theme tokens
  - consistent icon loader helper

---

## 8) Viewport look & feel (OpenGL)

### Current intent
Viewport lighting/material should look “CAD-like” on first frame.

### Target material
- Diffuse: ~0.8
- Ambient: ~0.2
- Specular: ~0.1
- Low shininess

### UX toggles to implement (UI only)
- “Technical Mode” (monochrome mesh)
- “Show edges” (edge overlay)
- “Wireframe”

### Selection visuals
- Hover highlight: accent @ ~40% alpha
- Selected: accent @ ~70% alpha
- Ensure selection is readable on dark background

---

## 9) Splash screen + About dialog

### Splash
- Minimal.
- Dark background.
- Logo + product name + tagline.
- Optional subtle wireframe fade.

### About dialog
Must include:
- Product name + version
- Build string
- OpenGL renderer/vendor/version
- Links: website, docs
- License tier placeholder (Standard/Advanced/Enterprise)

---

## 10) Implementation checklist (Codex execution order)

### Phase A — groundwork
1. Add `ui/theme/tokens.py` and `ui/theme/apply_theme.py`.
2. Add `ui/resources.qrc` and wire it into the app.
3. Add `ui/assets/` structure.

**Acceptance:** App launches with dark theme globally and no missing icons.

### Phase B — icon loader + replacement
1. Create `ui/icon_loader.py` helper:
   - loads from QRC
   - returns `QIcon`
   - can force pixmap sizes
2. Replace all existing icons with new monoline SVGs.

**Acceptance:** Ribbon/toolbars use consistent icons, no mixed styles.

### Phase C — ribbon spacing + hierarchy
1. Normalize button sizes and paddings.
2. Remove inconsistent margins.
3. Ensure disabled/hover/active states are visible.

**Acceptance:** Ribbon looks like industrial CAD UI (not prototype).

### Phase D — viewport styling
1. Adjust lighting/material defaults.
2. Add toggles in UI for Technical Mode, Edges, Wireframe.
3. Ensure selection colors align with theme accent.

**Acceptance:** Model depth readability is consistent; selection is obvious.

### Phase E — branding surfaces
1. Rename window title, splash, about text to **3DXFlat Advanced**.
2. Replace app icon.
3. Add `About` dialog with OpenGL info.

**Acceptance:** The app visually reads as a product with a consistent identity.

---

## 11) QA / Definition of Done

### Visual consistency
- No hardcoded widget colors outside theme module.
- All icons are from the same family.
- No missing assets when running from a clean machine.

### HiDPI
- Icons are crisp on 100% and 150% Windows scaling.

### Packaging readiness (UI side)
- All assets load from QRC.
- App icon is embedded and correct at multiple sizes.

---

## 12) Notes / References

- Windows icon guidance: ICO should include multiple sizes (16, 24, 32, 48, 64, 256). (Microsoft UX icon guidance)
- Qt icon handling: SVG should be added before non-SVG for correct icon engine selection. (Qt QIcon docs)
- Qt HiDPI SVG quirks exist; test toolbuttons at 24/32/48.

