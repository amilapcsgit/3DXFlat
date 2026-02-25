
## 2026-02-09 - [Restoring functional controls in unified layouts]
**Learning:** During UI unification/simplification, functional controls essential for the user's workflow (like seam allowance in CAD) are often hidden to achieve a "cleaner" aesthetic. Restoring these within the new hierarchy using consistent patterns (like "field shells") preserves usability without sacrificing the structural integrity of the design.
**Action:** Always audit hidden or "compatibility" widgets when working on a UI transition to ensure core functionality remains accessible.

## 2026-02-09 - [High-density CAD toolbar optimization]
**Learning:** In industrial applications with many actions, fixed-width buttons based on text labels can quickly exceed typical screen resolutions. Transitioning to a "flexible" minimum width or significantly reduced fixed minimum (e.g., 100px instead of 132px) while maintaining icons is necessary to prevent UI clipping and ensure all contextual tools remain visible.
**Action:** When designing toolbars with >10 actions, prioritize horizontal density by tightening shell margins and reducing button padding/min-widths early in the design phase.

## 2026-02-25 - [Compact UI and Typography Optimization]
**Learning:** For professional CAD applications, vertical real estate is at a premium. Reducing toolbars by ~30% and using a condensed font (Roboto Condensed) significantly improves the usable geometry workspace and reduces visual "bulk".
**Action:** When a UI feels "unbalanced" or "heavy", prefer compacting heights and using tighter typography before removing features.

## 2026-02-25 - [Structural vertical zoning for High-DPI CAD headers]
**Learning:** Professional industrial applications require distinct vertical zoning. A two-row header with a thin system bar (36px) for status/settings and a tall command bar (80px) for primary workflow tools (using text-under-icon styling) significantly improves readability and "gravity" of the interface on high-resolution displays.
**Action:** When a toolbar feels cluttered, move utility/status widgets to a dedicated top system bar and expand the main action buttons to a text-under-icon layout.
