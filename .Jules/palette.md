
## 2026-02-09 - [Restoring functional controls in unified layouts]
**Learning:** During UI unification/simplification, functional controls essential for the user's workflow (like seam allowance in CAD) are often hidden to achieve a "cleaner" aesthetic. Restoring these within the new hierarchy using consistent patterns (like "field shells") preserves usability without sacrificing the structural integrity of the design.
**Action:** Always audit hidden or "compatibility" widgets when working on a UI transition to ensure core functionality remains accessible.

## 2026-02-09 - [High-density CAD toolbar optimization]
**Learning:** In industrial applications with many actions, fixed-width buttons based on text labels can quickly exceed typical screen resolutions. Transitioning to a "flexible" minimum width or significantly reduced fixed minimum (e.g., 100px instead of 132px) while maintaining icons is necessary to prevent UI clipping and ensure all contextual tools remain visible.
**Action:** When designing toolbars with >10 actions, prioritize horizontal density by tightening shell margins and reducing button padding/min-widths early in the design phase.
