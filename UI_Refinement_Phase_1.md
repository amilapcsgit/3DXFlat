
# UI Refinement Phase 1 — 3DXFlat Advanced

## Objective
Elevate current UI from functional prototype to industrial-grade product appearance.
This phase focuses strictly on layout, spacing, hierarchy, and visual structure.
No algorithm or backend changes.

---

# 1️⃣ Global Layout Structure

## Top-Level Zones (Vertical Stack)

1. Title Bar (native OS)
2. Primary Command Ribbon (64px height)
3. Secondary Tool Strip (48px height)
4. Main Workspace (3D viewport + 2D panel split)
5. Status Bar (28px height)

Total vertical rhythm must follow 8px spacing grid.

---

# 2️⃣ Pixel & Spacing System (Strict Grid)

Base unit: 8px

Spacing tokens:
- XS = 4px
- S  = 8px
- M  = 16px
- L  = 24px
- XL = 32px

Corner radius:
- Buttons: 6px
- Panels: 8px

Border thickness:
- Panels: 1px
- Dividers: 1px (subtle)

---

# 3️⃣ Primary Ribbon Redesign (Industrial Workflow)

Current issue:
Buttons appear scattered and equal weight.
Hierarchy is unclear.

## New Logical Structure

Primary Ribbon (64px height)

LEFT GROUP — File Operations
--------------------------------
[ Import 3D ]

CENTER GROUP — Core Operation
--------------------------------
[ Run Flatten ]  ← Primary action (accent background)

RIGHT GROUP — Output
--------------------------------
[ Export DXF ]

Spacing:
- 24px padding from window edge (left/right)
- 32px between left, center, right groups
- Button internal padding: 12px horizontal, 8px vertical

Button sizes:
- Primary (Run Flatten): 120–140px width
- Secondary buttons: 110px width

Primary button styling:
- Background: ACCENT
- Text: White
- Slight elevation (subtle hover lightening only)
- No gradient

Secondary buttons:
- BG_PANEL background
- BORDER 1px
- Hover: BG_HOVER

---

# 4️⃣ Secondary Tool Strip (48px height)

Purpose:
Contextual tools for active tab (Setup / Flatten / Production)

Layout structure:
[ Section Title ]   [ Tools... ]

Example (Setup tab):

SECTION: Import
--------------------------------
| Import Model | Check Scale | Reset Camera | Toggle 2D Preview |

Spacing:
- 16px internal padding left/right
- 12px between buttons
- Section titles 12px Semibold
- Buttons fixed height: 32px

All icons must be 24px (future phase).

---

# 5️⃣ Main Workspace Layout

Split:
- 3D Viewport: 65%
- 2D Pattern Panel: 35%

Minimum 2D panel width: 420px

Panel padding:
- 16px internal margin

Panel background:
- BG_PANEL
- 1px BORDER separation

Panel header (2D):
Height: 36px
Contains:
- Title: "2D Pattern Preview (CAD)"
- Future zoom controls (right aligned)

Header padding:
- 16px left/right
- Title font: 13px Semibold

---

# 6️⃣ Viewport Visual Specification

3D Viewport:

Grid:
- Darken 10% compared to current
- Reduce contrast

Mesh default color:
- Neutral grey (#7A828C range)
- Selection only uses accent color

Selection alpha:
- Hover: 40%
- Selected: 70%

Floating toolbar:
- Width: 44px
- Button size: 36px square
- 8px spacing between buttons
- Panel radius: 10px

---

# 7️⃣ Status Bar (28px height)

Layout:
Left:
- Units + Scale info

Right:
- Mesh diagnostics (small secondary text)

Typography:
- 12px
- TEXT_SECONDARY color

Status bar must visually separate from workspace via 1px top border.

---

# 8️⃣ Typography Hierarchy

Ribbon buttons: 12px Medium
Section titles: 12px Semibold
Panel titles: 13px Semibold
Body text: 13px Regular
Diagnostics text: 12px Secondary color

No mixed font sizes outside this list.

---

# 9️⃣ Interaction Hierarchy Rules

Primary action:
- Only one accent-colored button visible per workflow state.

Secondary actions:
- Neutral background, subtle hover.

Tertiary actions:
- Icon-only, low contrast until hover.

---

# 🔟 Immediate Implementation Order

Phase 1 Tasks:

1. Rename window title to: 3DXFlat Advanced
2. Implement strict spacing grid (8px system).
3. Rebuild ribbon groups with left / center / right alignment.
4. Normalize button sizes (32px height for tool strip).
5. Restyle 2D panel with header strip.
6. Reduce mesh color intensity.
7. Update status bar alignment.

Acceptance Criteria:
- UI reads structured and calm.
- Clear visual hierarchy.
- No misaligned buttons.
- No inconsistent paddings.
- Primary action visually dominant.

---

End of Phase 1 Specification
