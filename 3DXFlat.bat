@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"
set "REPO_PATH=%CD%"
set "RUNTIME_LOG=%REPO_PATH%\runtimeloh.txt"
>"%RUNTIME_LOG%" echo === 3DXFlat runtime log ===

set "FORCE_INSTALL=0"
if /I "%~1"=="--force-install" set "FORCE_INSTALL=1"
if /I "%~1"=="--build-exe" (
  shift
  call "%~dp0build_exe.bat" %*
  exit /b !ERRORLEVEL!
)

set "BASE_PY="
set "PY_VER="
set "PY_EXE="
set "RECREATE_VENV=0"
set "IS_NETWORK_REPO=0"
set "DRIVE="
set "DRIVE_TYPE_LINE="

if "!REPO_PATH:~0,2!"=="\\" set "IS_NETWORK_REPO=1"
if "!IS_NETWORK_REPO!"=="0" (
  set "DRIVE=!REPO_PATH:~0,2!"
  for /f "delims=" %%D in ('fsutil fsinfo drivetype !DRIVE! 2^>nul') do set "DRIVE_TYPE_LINE=%%D"
  echo !DRIVE_TYPE_LINE! | find /I "Remote" >nul 2>&1
  if not errorlevel 1 set "IS_NETWORK_REPO=1"
)

if not defined LOCALAPPDATA set "LOCALAPPDATA=%TEMP%"
if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
if not defined LOCALAPPDATA set "LOCALAPPDATA=%CD%"

set "LOCAL_BASE=%LOCALAPPDATA%\3DXFlat"
if "!LOCAL_BASE!"=="\3DXFlat" set "LOCAL_BASE=%TEMP%\3DXFlat"
if "!LOCAL_BASE!"=="\3DXFlat" set "LOCAL_BASE=%REPO_PATH%\.3DXFlatLocal"

if "!IS_NETWORK_REPO!"=="1" (
  set "VENV_DIR=%LOCAL_BASE%\.venv"
) else (
  set "VENV_DIR=%REPO_PATH%\.venv"
)
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "REQ_HASH_FILE=%VENV_DIR%\.req_hash"

set "PIP_CACHE_DIR=%LOCAL_BASE%\pip-cache"
set "TMP=%LOCAL_BASE%\tmp"
set "TEMP=%LOCAL_BASE%\tmp"
set "TMPDIR=%LOCAL_BASE%\tmp"
if not exist "%LOCAL_BASE%" mkdir "%LOCAL_BASE%"
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if not exist "%TMP%" mkdir "%TMP%"

echo === 3DXFlat bootstrap ===
echo [1/5] Locating Python...
call :log "[1/5] Locating Python..."

call :find_python

if not defined BASE_PY (
  call :log "ERROR: Python 3.10+ not found in PATH."
  echo Python 3.10+ was not found.
  echo Install Python and enable "Add python.exe to PATH", then run again.
  echo Download: https://www.python.org/downloads/windows/
  echo See runtime log: %RUNTIME_LOG%
  pause
  exit /b 1
)

echo     Found Python %PY_VER% at %PY_EXE%
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
  if %%A GTR 3 echo WARNING: Python %PY_VER% detected. Wheels may be unstable; 3.10-3.13 is recommended.
  if %%A EQU 3 if %%B GEQ 14 echo WARNING: Python %PY_VER% detected. Wheels may be unstable; 3.10-3.13 is recommended.
)

echo [2/5] Resolving virtual environment path...
if "%IS_NETWORK_REPO%"=="1" (
  echo     Repo is UNC/network-backed. Using local venv: %VENV_DIR%
  call :log "[2/5] Network repo detected. Using local venv: %VENV_DIR%"
) else (
  echo     Using repo venv: %VENV_DIR%
  call :log "[2/5] Using repo venv: %VENV_DIR%"
)

if exist "%VENV_PY%" (
  "%VENV_PY%" -c "import sys; print(sys.executable)" >nul 2>&1
  if errorlevel 1 (
    echo [3/5] Existing virtual environment is invalid. Recreating...
    set "RECREATE_VENV=1"
  ) else (
    echo [3/5] Using existing virtual environment...
  )
) else (
  echo [3/5] Virtual environment not found. Creating...
  set "RECREATE_VENV=1"
)

if "%RECREATE_VENV%"=="1" (
  if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
  for %%I in ("%VENV_DIR%") do if not exist "%%~dpI" mkdir "%%~dpI"
  call :log "CMD START: \"%BASE_PY%\" -m venv \"%VENV_DIR%\""
  "%BASE_PY%" -m venv "%VENV_DIR%" >>"%RUNTIME_LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  call :log "CMD END rc=!RC!"
  if not "!RC!"=="0" (
    call :log "ERROR: Failed to create virtual environment."
    echo Failed to create virtual environment.
    echo See runtime log: %RUNTIME_LOG%
    pause
    exit /b 1
  )
)

if not exist "%VENV_PY%" (
  call :log "ERROR: Venv python missing: %VENV_PY%"
  echo Virtual environment python executable not found: %VENV_PY%
  echo See runtime log: %RUNTIME_LOG%
  pause
  exit /b 1
)

if not exist "requirements.txt" (
  call :log "ERROR: requirements.txt not found."
  echo requirements.txt not found in repo root.
  echo See runtime log: %RUNTIME_LOG%
  pause
  exit /b 1
)

call :compute_req_hash "requirements.txt"
if not defined REQ_HASH (
  call :log "ERROR: Failed to compute requirements hash."
  echo Failed to compute requirements hash.
  echo See runtime log: %RUNTIME_LOG%
  pause
  exit /b 1
)

set "NEED_INSTALL=1"
if "%FORCE_INSTALL%"=="1" (
  echo [4/5] Force install requested: --force-install
) else (
  if exist "%REQ_HASH_FILE%" (
    set "OLD_REQ_HASH="
    set /p OLD_REQ_HASH=<"%REQ_HASH_FILE%"
    if /I "%OLD_REQ_HASH%"=="%REQ_HASH%" set "NEED_INSTALL=0"
  )
  if "%NEED_INSTALL%"=="0" (
    echo [4/5] requirements unchanged. Skipping dependency install.
  ) else (
    echo [4/5] Installing/updating dependencies...
  )
)

if "%NEED_INSTALL%"=="1" (
  call :log "CMD START: \"%VENV_PY%\" -m pip install --upgrade pip setuptools wheel"
  "%VENV_PY%" -m pip install --upgrade pip setuptools wheel >>"%RUNTIME_LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  call :log "CMD END rc=!RC!"
  if not "!RC!"=="0" (
    call :log "ERROR: Failed to upgrade pip tooling."
    echo Failed to upgrade pip tooling.
    echo See runtime log: %RUNTIME_LOG%
    pause
    exit /b 1
  )

  call :log "CMD START: \"%VENV_PY%\" -m pip install -r requirements.txt"
  "%VENV_PY%" -m pip install -r requirements.txt >>"%RUNTIME_LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  call :log "CMD END rc=!RC!"
  if not "!RC!"=="0" (
    call :log "ERROR: Failed to install requirements."
    echo Failed to install requirements.
    echo See runtime log: %RUNTIME_LOG%
    pause
    exit /b 1
  )

  call :log "CMD START: \"%VENV_PY%\" -c \"import customtkinter, PySide6, pyqtgraph, OpenGL, gmsh, igl\""
  "%VENV_PY%" -c "import customtkinter, PySide6, pyqtgraph, OpenGL, gmsh, igl" >>"%RUNTIME_LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  call :log "CMD END rc=!RC!"
  if not "!RC!"=="0" (
    call :log "WARN: Dependency sanity check failed. Continuing launch."
    echo WARNING: Dependency sanity check failed. Continuing launch attempt.
  )

  >"%REQ_HASH_FILE%" echo %REQ_HASH%
)

echo [5/5] Running 3DXFlat...
call :log "[5/5] Running main.py (Qt preferred, Tk fallback allowed)..."
set "THREEDXFLAT_FORCE_QT="
set "THREEDXFLAT_FORCE_TK="

call :log "CMD START: \"%VENV_PY%\" main.py"
"%VENV_PY%" main.py >>"%RUNTIME_LOG%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
call :log "CMD END rc=%EXIT_CODE%"

if not "%EXIT_CODE%"=="0" (
  call :log "Qt run failed rc=%EXIT_CODE%. Trying Tk fallback."
  echo     Qt/OpenGL launch failed, trying legacy fallback UI...
  set "THREEDXFLAT_FORCE_TK=1"
  call :log "CMD START: \"%VENV_PY%\" main.py (THREEDXFLAT_FORCE_TK=1)"
  "%VENV_PY%" main.py >>"%RUNTIME_LOG%" 2>&1
  set "EXIT_CODE=!ERRORLEVEL!"
  call :log "CMD END rc=!EXIT_CODE!"
)

if not "%EXIT_CODE%"=="0" (
  call :log "ERROR: Final exit code %EXIT_CODE%"
  echo.
  echo 3DXFlat exited with code %EXIT_CODE%.
  echo Check runtime log: %RUNTIME_LOG%
  pause
)

exit /b %EXIT_CODE%

:find_python
set "BASE_PY="
set "PY_VER="
set "PY_EXE="

if defined PYTHON_EXE call :accept_python "%PYTHON_EXE%"

if not defined BASE_PY (
  where.exe py >nul 2>&1
  if not errorlevel 1 (
    set "CAND_EXE="
    for /f "usebackq delims=" %%P in (`py -3.13 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined CAND_EXE set "CAND_EXE=%%P"
    if defined CAND_EXE call :accept_python "!CAND_EXE!"
    if not defined BASE_PY (
      set "CAND_EXE="
      for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined CAND_EXE set "CAND_EXE=%%P"
      if defined CAND_EXE call :accept_python "!CAND_EXE!"
    )
  )
)

if not defined BASE_PY (
  where.exe python >nul 2>&1
  if not errorlevel 1 (
    for /f "usebackq delims=" %%P in (`where.exe python 2^>nul`) do (
      if not defined BASE_PY call :accept_python "%%P"
    )
  )
)

if not defined BASE_PY call :accept_python "%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined BASE_PY call :accept_python "%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined BASE_PY call :accept_python "C:\Python313\python.exe"
if not defined BASE_PY call :accept_python "C:\Python312\python.exe"
goto :eof

:accept_python
set "CAND_EXE=%~1"
if not defined CAND_EXE goto :eof
if not exist "%CAND_EXE%" goto :eof
"%CAND_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
for /f "tokens=2 delims= " %%V in ('"%CAND_EXE%" -V 2^>^&1') do set "CAND_VER=%%V"
set "BASE_PY=%CAND_EXE%"
set "PY_EXE=%CAND_EXE%"
set "PY_VER=%CAND_VER%"
goto :eof

:compute_req_hash
set "REQ_HASH="
for /f "skip=1 tokens=1" %%H in ('certutil -hashfile "%~1" SHA256 ^| findstr /R /I "^[0-9A-F][0-9A-F]"') do (
  if not defined REQ_HASH set "REQ_HASH=%%H"
)
goto :eof

:log
>>"%RUNTIME_LOG%" echo [%DATE% %TIME%] %*
goto :eof
