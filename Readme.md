# 3DXFlat Advanced (Qt + OpenGL)

3DXFlat Advanced is a CAD-oriented workflow for panel fabrication:
import 3D geometry, inspect/select surfaces, flatten to 2D, and export production DXF.

## Current Scope

- Qt ribbon workspace with Setup / Flatten / Production flow.
- OpenGL 3D viewport (`GLViewWidget`) with GPU rendering, ViewCube camera presets, HUD controls, and split 3D/2D preview.
- STEP import path with fallback meshing through `gmsh`.
- Flattening workflow (LSCM / ARAP) + DXF export.
- Nesting pipeline integration.

## Technologies Used

- UI: `PySide6`, `qt-material`
- 3D viewport: `pyqtgraph.opengl`, `PyOpenGL`, `numpy`
- Mesh IO / geometry: `trimesh`, `gmsh`, `libigl`
- 2D / export / nesting: `ezdxf`, `shapely`, `networkx`, `scipy`, `svgwrite`

## Supported Import Formats

- STL (`.stl`)
- OBJ (`.obj`)
- STEP (`.stp`, `.step`)

## Install

```bash
python -m pip install -r requirements.txt
```

## Run

Windows launcher (recommended):

```powershell
.\3DXFlat.bat
```

This bootstrap launcher creates `.venv` (if missing), installs requirements, and starts the Qt/OpenGL UI.

Default Python entrypoint:

```bash
python main.py
```

Force Tkinter fallback:

```powershell
$env:THREEDXFLAT_FORCE_TK = "1"
python main.py
```

Direct Tkinter app:

```bash
python gui.py
```

## Quick Test (Fresh Venv)

```powershell
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:THREEDXFLAT_FORCE_QT = "1"
.\.venv\Scripts\python.exe main.py
```
