# Industrial CAD Theme v1 — 3DXFlat Advanced (Codex)

Goal: **Dark chrome + Light 3D viewport + Dark 2D panel** (hybrid CAD look).
This theme is designed to reduce fatigue and maximize geometry readability.

---

## 1) Core Color Tokens

> Keep these as the **single source of truth**. No hardcoded colors in widgets.

### Dark UI chrome (Qt)

- `BG_MAIN`      = `#1F2227`
- `BG_PANEL`     = `#2A2F36`
- `BG_HOVER`     = `#323842`
- `BORDER`       = `#3A4048`
- `TEXT_PRIMARY` = `#E5E9F0`
- `TEXT_SECOND`  = `#9AA4B2`
- `DISABLED`     = `#6B7480`
- `ACCENT`       = `#00AEEF`
- `ERROR`        = `#E74C3C`

### 3D viewport (OpenGL) — light CAD

- `VP_BG`        = `#E6E9ED`
- `GRID_MINOR`   = `#D0D5DB`
- `GRID_MAJOR`   = `#B7BDC5`
- `MESH_DIFFUSE` = `#7E8896`
- `EDGE`         = `#3A4048` (use alpha)
- `SEL`          = `#00AEEF` (use alpha)

### 2D preview (dark)

- `P2D_BG`       = `#1D2127`
- `P2D_GRID`     = `#2A2F36` (optional faint)
- `P2D_OUTER`    = `#00AEEF`
- `P2D_INNER`    = `#E74C3C`

---

## 2) Typography

- Base: `Segoe UI` (Windows) / fallback `DejaVu Sans`
- Buttons: 12–13px Medium/Bold
- Section labels: 12px Semibold
- Diagnostics: 12px Regular, `TEXT_SECOND`

---

## 3) Spacing + Geometry (8px Grid)

- Base grid: 8px
- `XS=4` `S=8` `M=16` `L=24` `XL=32`
- Button height (tool strip): **32px**
- Primary ribbon height: **64px**
- Tabs row: **32px**
- Status bar: **28px**
- Panel header: **36px**
- Button radius: **6px**
- Panel radius: **8px**
- Floating tool panel radius: **10px**

---

## 4) Qt Palette (C) — Hybrid UI Shell

Use palette + stylesheet. Palette sets defaults, QSS refines.

### PySide6 / PyQt example

```python
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

def apply_dark_chrome(app):
    pal = QPalette()

    BG_MAIN      = QColor("#1F2227")
    BG_PANEL     = QColor("#2A2F36")
    BORDER       = QColor("#3A4048")
    TEXT_PRIMARY = QColor("#E5E9F0")
    TEXT_SECOND  = QColor("#9AA4B2")
    ACCENT       = QColor("#00AEEF")

    pal.setColor(QPalette.Window, BG_MAIN)
    pal.setColor(QPalette.Base, BG_PANEL)
    pal.setColor(QPalette.AlternateBase, BG_MAIN)
    pal.setColor(QPalette.ToolTipBase, BG_PANEL)
    pal.setColor(QPalette.ToolTipText, TEXT_PRIMARY)
    pal.setColor(QPalette.Text, TEXT_PRIMARY)
    pal.setColor(QPalette.WindowText, TEXT_PRIMARY)
    pal.setColor(QPalette.Button, BG_PANEL)
    pal.setColor(QPalette.ButtonText, TEXT_PRIMARY)
    pal.setColor(QPalette.Highlight, ACCENT)
    pal.setColor(QPalette.HighlightedText, QColor("#0B0F14"))

    app.setPalette(pal)
```

### Minimal QSS (recommended)

```css
/* Apply to the shell (ribbon, panels, status) */
QWidget { color: #E5E9F0; }
QMainWindow { background: #1F2227; }

/* Panels */
QFrame, QGroupBox {
  background: #2A2F36;
  border: 1px solid #3A4048;
  border-radius: 8px;
}

/* Toolbars / ribbon containers */
QToolBar, QTabBar, QMenuBar {
  background: #1F2227;
  border: none;
}

/* Buttons */
QPushButton {
  background: #2A2F36;
  border: 1px solid #3A4048;
  border-radius: 6px;
  padding: 8px 12px;
}
QPushButton:hover { background: #323842; }
QPushButton:disabled { color: #6B7480; border-color: #2A2F36; }

/* Primary action class */
QPushButton#primaryAction {
  background: #00AEEF;
  border: none;
  color: white;
}
QPushButton#primaryAction:hover { background: #17B6F0; }

/* Status bar */
QStatusBar {
  background: #1F2227;
  border-top: 1px solid #3A4048;
  color: #9AA4B2;
}
```

### IMPORTANT: keep the 3D viewport light
Do **not** inherit the dark palette into the OpenGL viewport.
Explicitly set the viewport clear color in OpenGL (see below).

---

## 5) OpenGL / Rendering Params (B) — Light CAD Viewport

### Background + grid
- Clear color: `VP_BG = #E6E9ED`
- Grid:
  - minor: `#D0D5DB` (alpha 0.55)
  - major: `#B7BDC5` (alpha 0.75)

### Mesh material (default)
- diffuse: `#7E8896`
- ambient: 0.20
- specular: 0.08
- shininess: 16–24 (low)
- edges: `#3A4048` alpha 0.35

### Selection / hover
- hover: `ACCENT` alpha 0.40
- selected: `ACCENT` alpha 0.70
- optional: outline edge thicker by +0.5px on selection

### Pseudocode (OpenGL)
```cpp
glClearColor(230/255.f, 233/255.f, 237/255.f, 1.0f); // #E6E9ED

mesh.diffuse   = vec3(126,136,150)/255.0;
mesh.ambientK  = 0.20;
mesh.specularK = 0.08;
mesh.shininess = 20.0;

grid.minor = vec4(208,213,219, 0.55);
grid.major = vec4(183,189,197, 0.75);

edge.color = vec4(58,64,72, 0.35);
sel.color  = vec4(0,174,239, 0.70);
hover.color= vec4(0,174,239, 0.40);
```

---

## 6) 2D Preview Theme (Dark)

- Background: `#1D2127`
- Keep outlines crisp:
  - outer boundary: `#00AEEF` (alpha 0.95)
  - inner/offset line: `#E74C3C` (alpha 0.85)
- Optional faint grid: `#2A2F36` alpha 0.25

---

## 7) Implementation Order (Codex)

1. Create `ui/theme/tokens.(py|h|json)` with all hex values above.
2. Apply `apply_dark_chrome(app)` at startup.
3. Apply QSS (as a file) after palette.
4. In OpenGL widget init:
   - set clear color to `VP_BG`
   - update grid colors/opacities
   - set default mesh material to neutral grey
   - accent only for hover/selection
5. Keep 2D preview dark, add a 36px header strip (Phase 1 spec).
6. Only after this: wire SVG icon set.

---

## 8) Acceptance Criteria

- UI shell stays dark and consistent (no random greys).
- 3D viewport is light, CAD-like, readable.
- Selection color is the only strong accent.
- Grid does not overpower geometry.
- 2D panel remains dark and contrasts clearly with 3D.

