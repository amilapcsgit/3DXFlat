
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

## 2026-02-25 - [Preventing label clipping in high-density QToolButton layouts]
**Learning:** When using `ToolButtonTextUnderIcon` style in high-density CAD headers, standard vertical spacing is often insufficient. Qt may silently hide labels if the button geometry is even 1-2 pixels too small. Increasing container height (e.g., from 80px to 90px) and explicitly resetting margins/padding on individual buttons is necessary to guarantee text visibility across different OS scaling settings.
**Action:** Always provide at least 10-15px of vertical "buffer" beyond the icon+label height when using stacked button layouts.

## 2026-02-25 - [Resolving icon symlink failures in Qt]
**Learning:** Qt's `QIcon` and standard file reading may fail to resolve symbolic links on certain platforms or restricted environments (like some sandbox containers). Using `os.path.realpath()` to resolve the absolute path before passing it to Qt or `Path.read_text()` ensures that the actual asset is found and loaded correctly.
**Action:** Always wrap filesystem-based asset paths in `os.path.realpath()` when loading icons or configuration files.

## 2026-02-25 - [Optimizing CAD button typography for density]
**Learning:** In high-density industrial headers, font size alone doesn't guarantee readability. Moving from 9pt to 11pt Bold (700) while simultaneously reducing icon size (e.g., from 32px to 28px) creates the necessary vertical separation for rapid scanning of primary actions.
**Action:** For primary CTA buttons, prioritize bold typography over large icons to improve cognitive "pop" in complex toolbars.
