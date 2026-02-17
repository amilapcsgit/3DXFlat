# PLAN.md - 3DXFlat Standalone Prep (Local)

Date executed: 2026-02-17  
Workspace: `C:\Users\Amilapcs\source\repos\3DXFlat`

## 1) Repo Hygiene (Completed)

Actions:
- Removed compiled artifacts from `flatten_surface/__pycache__/`.
- Verified no committed `*.pyc` artifacts remain.
- Ensured `.gitignore` includes:
  - `flatten_surface/__pycache__/`
  - `*.pyc`

## 2) Branding Pass (Completed)

Actions:
- Product name standardized to `3DXFlat` in launcher/docs strings.
- Legacy launcher naming removed from primary startup path.

Launcher updates:
- Renamed `tent_maker_pro.bat` to `3DXFlat.bat`.
- Updated `run.bat` to delegate to `3DXFlat.bat` (compatibility path now uses same startup behavior).

## 3) Legal / Notices (Completed)

Actions:
- `THIRD_PARTY_NOTICES.md` remains dependency-based and does not claim authorship of third-party components.
- No vendored third-party source folders were found that needed extra attribution blocks.

## 4) Runtime Verification (Completed)

Fresh venv and install verification:
```powershell
cmd /c "rmdir /s /q .venv"
cmd /c 3DXFlat.bat
```

Observed behavior:
- `.venv` was created successfully.
- `pip`, `setuptools`, and `wheel` were upgraded.
- `requirements.txt` dependencies installed successfully.
- Qt launch was forced (no silent Tk fallback).

Qt startup bug fixed during verification:
- Initial forced-Qt launch exposed a runtime error: `name 'background' is not defined`.
- Root cause: unescaped braces in f-string stylesheet blocks in `qt_app/viewport.py`.
- Fix applied by escaping literal CSS braces in HUD/floating-orbit styles.

Post-fix launch checks:
```powershell
$env:THREEDXFLAT_FORCE_QT='1'
.\.venv\Scripts\python.exe main.py
```

Smoke result:
- Qt/OpenGL app process started successfully (`FORCE_QT_STARTED_OK` check).
- Batch launcher start path also validated (`BATCH_QT_RUNNING_CHILD_PYTHON` check).

## 5) Quick Test Commands (Verified)

Exact reproducible commands:
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:THREEDXFLAT_FORCE_QT = "1"
.\.venv\Scripts\python.exe main.py
```

One-click Windows launcher:
```powershell
.\3DXFlat.bat
```

## Assumptions (Best-Effort)

- Python 3.10+ is installed and available via `py -3` or `python`.
- Network access is available for `pip install -r requirements.txt`.
- Target PC has GPU/driver support for Qt OpenGL rendering.
