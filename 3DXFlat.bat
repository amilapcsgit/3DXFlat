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
set "PY_MAJMIN="
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
  set "VENV_DIR=%LOCAL_BASE%\.venv-py312"
) else (
  set "VENV_DIR=%REPO_PATH%\.venv-py312"
)
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "REQ_HASH_FILE=%VENV_DIR%\.req_hash"

set "PIP_CACHE_DIR=%LOCAL_BASE%\pip-cache"
set "TMP=%LOCAL_BASE%\tmp"
set "TEMP=%LOCAL_BASE%\tmp"
set "TMPDIR=%LOCAL_BASE%\tmp"
set "OPTIONAL_BREP_REQ=requirements-optional-brep.txt"
set "PORTABLE_PY_VERSION=3.12.8"
set "PORTABLE_PY_ROOT=%LOCAL_BASE%\python-%PORTABLE_PY_VERSION%-nuget"
set "PORTABLE_PY_EXE=%PORTABLE_PY_ROOT%\tools\python.exe"
if defined USERPROFILE (
  set "MAMBA_BASE=%USERPROFILE%\3DXF"
) else (
  set "MAMBA_BASE=%LOCAL_BASE%\3DXF"
)
if "!MAMBA_BASE!"=="\3DXF" set "MAMBA_BASE=%LOCAL_BASE%\3DXF"
set "MAMBA_ROOT=%MAMBA_BASE%\bin"
set "MAMBA_EXE=%MAMBA_ROOT%\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%MAMBA_BASE%\r"
set "MAMBA_ENV_PREFIX=%MAMBA_BASE%\e312"
set "MAMBA_ENV_PY=%MAMBA_ENV_PREFIX%\python.exe"
set "USING_MAMBA_RUNTIME=0"
set "OCC_OVERLAY_ENABLED=0"
set "OCC_OVERLAY_SITE=%LOCAL_BASE%\occ-overlay"
if not exist "%LOCAL_BASE%" mkdir "%LOCAL_BASE%"
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if not exist "%TMP%" mkdir "%TMP%"

echo === 3DXFlat bootstrap ===
echo [1/5] Locating Python...
call :log "[1/5] Locating Python..."

call :find_python

if not defined BASE_PY (
  echo     Python 3.12 not found on host. Bootstrapping local portable Python %PORTABLE_PY_VERSION%...
  call :log "INFO: Host Python 3.12 not found. Bootstrapping local portable Python %PORTABLE_PY_VERSION%."
  call :ensure_local_python_312
)

if not defined BASE_PY (
  call :log "ERROR: Could not resolve Python 3.12 (host or local portable)."
  echo Could not resolve Python 3.12, host or local portable bootstrap.
  echo Install Python 3.12 or check network access to nuget.org, then run again.
  echo See runtime log: %RUNTIME_LOG%
  pause
  exit /b 1
)

echo     Found Python %PY_VER% at %PY_EXE%
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
  set "PY_MAJMIN=%%A.%%B"
)
if /I not "!PY_MAJMIN!"=="3.12" (
  call :log "ERROR: Python %PY_VER% detected; Python 3.12.x is required."
  echo Python %PY_VER% detected at %PY_EXE%.
  echo This build requires Python 3.12.x for OCC compatibility.
  echo See runtime log: %RUNTIME_LOG%
  pause
  exit /b 1
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

  call :log "CMD START: \"%VENV_PY%\" -c \"import PySide6, pyqtgraph, OpenGL, gmsh, igl\""
  "%VENV_PY%" -c "import PySide6, pyqtgraph, OpenGL, gmsh, igl" >>"%RUNTIME_LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  call :log "CMD END rc=!RC!"
  if not "!RC!"=="0" (
    call :log "WARN: Dependency sanity check failed. Continuing launch."
    echo WARNING: Dependency sanity check failed. Continuing launch attempt.
  )

  >"%REQ_HASH_FILE%" echo %REQ_HASH%
)

if exist "%OPTIONAL_BREP_REQ%" (
  set "BREP_IMPORT_OK=0"
  call :check_occ "%VENV_PY%"
  if "!BREP_IMPORT_OK!"=="1" (
    echo [4.1/5] B-Rep dependency present: OpenCascade.
  ) else (
    echo [4.1/5] Provisioning B-Rep runtime ^(OpenCascade via micromamba^)...
    call :log "INFO: OCC not available in current venv. Provisioning local micromamba runtime."
    call :ensure_mamba_occ_runtime
    if not "!USING_MAMBA_RUNTIME!"=="1" (
      call :log "ERROR: Mandatory B-Rep dependency install failed."
      echo ERROR: Failed to provision mandatory B-Rep dependency.
      echo        STEP/IGES import requires OpenCascade runtime.
      echo        See runtime log: %RUNTIME_LOG%
      pause
      exit /b 1
    )
    call :enable_occ_overlay
    set "BREP_IMPORT_OK=0"
    call :check_occ "%VENV_PY%"
    if not "!BREP_IMPORT_OK!"=="1" (
      call :log "ERROR: OCC runtime is present but not importable from app venv."
      echo ERROR: OpenCascade runtime was provisioned but cannot be imported by app Python.
      echo        See runtime log: %RUNTIME_LOG%
      pause
      exit /b 1
    )
  )
) else (
  call :log "ERROR: %OPTIONAL_BREP_REQ% not found."
  echo ERROR: %OPTIONAL_BREP_REQ% not found.
  echo        STEP/IGES import requires pythonocc-core.
  echo        See runtime log: %RUNTIME_LOG%
  pause
  exit /b 1
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

if defined PYTHON_EXE call :accept_python_312 "%PYTHON_EXE%"

if not defined BASE_PY (
  where.exe python >nul 2>&1
  if not errorlevel 1 (
    for /f "usebackq delims=" %%P in (`where.exe python 2^>nul`) do (
      if not defined BASE_PY call :accept_python_312 "%%P"
    )
  )
)

if not defined BASE_PY call :accept_python_312 "%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined BASE_PY call :accept_python_312 "C:\Python312\python.exe"
goto :eof

:ensure_local_python_312
if exist "%PORTABLE_PY_EXE%" (
  call :accept_python_312 "%PORTABLE_PY_EXE%"
  if defined BASE_PY goto :eof
)

set "PORTABLE_PKG_URL=https://www.nuget.org/api/v2/package/python/%PORTABLE_PY_VERSION%"
set "PORTABLE_PKG_NUPKG=%TMP%\python-%PORTABLE_PY_VERSION%.nupkg"
set "PORTABLE_PKG_ZIP=%TMP%\python-%PORTABLE_PY_VERSION%.zip"
set "PORTABLE_BOOTSTRAP_PS=%TMP%\bootstrap_py312.ps1"

>"%PORTABLE_BOOTSTRAP_PS%" echo $ErrorActionPreference = 'Stop'
>>"%PORTABLE_BOOTSTRAP_PS%" echo $pkgUrl = '%PORTABLE_PKG_URL%'
>>"%PORTABLE_BOOTSTRAP_PS%" echo $pkgNupkg = '%PORTABLE_PKG_NUPKG%'
>>"%PORTABLE_BOOTSTRAP_PS%" echo $pkgZip = '%PORTABLE_PKG_ZIP%'
>>"%PORTABLE_BOOTSTRAP_PS%" echo $dest = '%PORTABLE_PY_ROOT%'
>>"%PORTABLE_BOOTSTRAP_PS%" echo if ^(Test-Path $pkgNupkg^) { Remove-Item $pkgNupkg -Force }
>>"%PORTABLE_BOOTSTRAP_PS%" echo if ^(Test-Path $pkgZip^) { Remove-Item $pkgZip -Force }
>>"%PORTABLE_BOOTSTRAP_PS%" echo Invoke-WebRequest -Uri $pkgUrl -OutFile $pkgNupkg
>>"%PORTABLE_BOOTSTRAP_PS%" echo Copy-Item $pkgNupkg $pkgZip -Force
>>"%PORTABLE_BOOTSTRAP_PS%" echo if ^(Test-Path $dest^) { Remove-Item $dest -Recurse -Force }
>>"%PORTABLE_BOOTSTRAP_PS%" echo Expand-Archive -Path $pkgZip -DestinationPath $dest -Force

call :log "CMD START: powershell -NoProfile -ExecutionPolicy Bypass -File \"%PORTABLE_BOOTSTRAP_PS%\""
powershell -NoProfile -ExecutionPolicy Bypass -File "%PORTABLE_BOOTSTRAP_PS%" >>"%RUNTIME_LOG%" 2>&1
set "RC=%ERRORLEVEL%"
call :log "CMD END rc=%RC%"
if not "%RC%"=="0" (
  call :log "ERROR: Local portable Python bootstrap failed."
  goto :eof
)

if exist "%PORTABLE_PY_EXE%" (
  call :accept_python_312 "%PORTABLE_PY_EXE%"
)
goto :eof

:ensure_mamba_occ_runtime
set "USING_MAMBA_RUNTIME=0"
set "ACTIVE_MAMBA_ROOT=%MAMBA_ROOT_PREFIX%"
set "ACTIVE_MAMBA_ENV=%MAMBA_ENV_PREFIX%"
set "ACTIVE_MAMBA_PY=%ACTIVE_MAMBA_ENV%\python.exe"

if exist "%ACTIVE_MAMBA_PY%" (
  call :check_occ "%ACTIVE_MAMBA_PY%"
  if "!BREP_IMPORT_OK!"=="1" (
    set "MAMBA_ROOT_PREFIX=%ACTIVE_MAMBA_ROOT%"
    set "MAMBA_ENV_PREFIX=%ACTIVE_MAMBA_ENV%"
    set "MAMBA_ENV_PY=%ACTIVE_MAMBA_PY%"
    set "USING_MAMBA_RUNTIME=1"
    call :log "INFO: Reusing existing micromamba runtime with OCC."
    goto :eof
  )
)

call :bootstrap_mamba_binary
if not "%RC%"=="0" (
  goto :eof
)

call :create_mamba_occ_env "%ACTIVE_MAMBA_ROOT%" "%ACTIVE_MAMBA_ENV%"
if "!RC!"=="0" goto :mamba_env_created

call :log "WARN: micromamba OCC env creation failed in primary prefix. Retrying with fresh prefix."
set "ACTIVE_MAMBA_ROOT=%MAMBA_BASE%\r2"
set "ACTIVE_MAMBA_ENV=%MAMBA_BASE%\e312b"
call :cleanup_mamba_prefix "%ACTIVE_MAMBA_ROOT%" "%ACTIVE_MAMBA_ENV%"
call :create_mamba_occ_env "%ACTIVE_MAMBA_ROOT%" "%ACTIVE_MAMBA_ENV%"
if not "!RC!"=="0" (
  call :log "ERROR: micromamba OCC env creation failed after retry."
  goto :eof
)

:mamba_env_created
set "ACTIVE_MAMBA_PY=%ACTIVE_MAMBA_ENV%\python.exe"
if not exist "%ACTIVE_MAMBA_PY%" (
  if exist "%ACTIVE_MAMBA_ENV%\Scripts\python.exe" set "ACTIVE_MAMBA_PY=%ACTIVE_MAMBA_ENV%\Scripts\python.exe"
)

if not exist "%ACTIVE_MAMBA_PY%" (
  set "RC=1"
  call :log "ERROR: micromamba env python not found."
  goto :eof
)

set "MAMBA_ROOT_PREFIX=%ACTIVE_MAMBA_ROOT%"
set "MAMBA_ENV_PREFIX=%ACTIVE_MAMBA_ENV%"
set "MAMBA_ENV_PY=%ACTIVE_MAMBA_PY%"

call :check_occ "%MAMBA_ENV_PY%"
if not "!BREP_IMPORT_OK!"=="1" (
  set "RC=1"
  call :log "ERROR: micromamba env created but OCC import failed."
  goto :eof
)

call :check_occ "%MAMBA_ENV_PY%"
if "!BREP_IMPORT_OK!"=="1" (
  set "RC=0"
  set "USING_MAMBA_RUNTIME=1"
  call :log "INFO: OCC runtime available from micromamba env: %MAMBA_ENV_PY%"
  goto :eof
)

set "RC=1"
call :log "ERROR: OCC import failed after micromamba runtime provisioning."
goto :eof

:bootstrap_mamba_binary
set "RC=0"
if exist "%MAMBA_EXE%" goto :mamba_binary_check

if not exist "%MAMBA_ROOT%" mkdir "%MAMBA_ROOT%"
set "MAMBA_BOOTSTRAP_PS=%TMP%\bootstrap_micromamba.ps1"
>"%MAMBA_BOOTSTRAP_PS%" echo $ErrorActionPreference = 'Stop'
>>"%MAMBA_BOOTSTRAP_PS%" echo $url = 'https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-win-64'
>>"%MAMBA_BOOTSTRAP_PS%" echo $exe = '%MAMBA_EXE%'
>>"%MAMBA_BOOTSTRAP_PS%" echo New-Item -ItemType Directory -Force -Path ^(Split-Path $exe^) ^| Out-Null
>>"%MAMBA_BOOTSTRAP_PS%" echo Invoke-WebRequest -Uri $url -OutFile $exe
call :log "CMD START: powershell -NoProfile -ExecutionPolicy Bypass -File \"%MAMBA_BOOTSTRAP_PS%\""
powershell -NoProfile -ExecutionPolicy Bypass -File "%MAMBA_BOOTSTRAP_PS%" >>"%RUNTIME_LOG%" 2>&1
set "RC=%ERRORLEVEL%"
call :log "CMD END rc=%RC%"
if not "%RC%"=="0" (
  call :log "ERROR: micromamba bootstrap failed."
  goto :eof
)

:mamba_binary_check
call :log "CMD START: \"%MAMBA_EXE%\" --version"
"%MAMBA_EXE%" --version >>"%RUNTIME_LOG%" 2>&1
set "RC=%ERRORLEVEL%"
call :log "CMD END rc=%RC%"
if not "%RC%"=="0" call :log "ERROR: micromamba binary check failed."
goto :eof

:create_mamba_occ_env
set "RC=1"
set "CREATE_ROOT=%~1"
set "CREATE_ENV=%~2"
if not defined CREATE_ROOT goto :eof
if not defined CREATE_ENV goto :eof
if not exist "%CREATE_ROOT%" mkdir "%CREATE_ROOT%"
call :log "CMD START: \"%MAMBA_EXE%\" create -y -r \"%CREATE_ROOT%\" -p \"%CREATE_ENV%\" -c conda-forge python=3.12 pythonocc-core pip"
"%MAMBA_EXE%" create -y -r "%CREATE_ROOT%" -p "%CREATE_ENV%" -c conda-forge python=3.12 pythonocc-core pip >>"%RUNTIME_LOG%" 2>&1
set "RC=%ERRORLEVEL%"
call :log "CMD END rc=%RC%"
goto :eof

:ensure_mamba_env_pip
set "RC=1"
call :log "CMD START: \"%MAMBA_ENV_PY%\" -m pip --version"
"%MAMBA_ENV_PY%" -m pip --version >>"%RUNTIME_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :log "CMD END rc=!RC!"
if "!RC!"=="0" goto :eof

call :log "WARN: pip is missing in micromamba env; installing pip package."
call :log "CMD START: \"%MAMBA_EXE%\" install -y -r \"%MAMBA_ROOT_PREFIX%\" -p \"%MAMBA_ENV_PREFIX%\" -c conda-forge pip python=3.12"
"%MAMBA_EXE%" install -y -r "%MAMBA_ROOT_PREFIX%" -p "%MAMBA_ENV_PREFIX%" -c conda-forge pip python=3.12 >>"%RUNTIME_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :log "CMD END rc=!RC!"
if not "!RC!"=="0" goto :eof

call :log "CMD START: \"%MAMBA_ENV_PY%\" -m pip --version"
"%MAMBA_ENV_PY%" -m pip --version >>"%RUNTIME_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :log "CMD END rc=!RC!"
if "!RC!"=="0" goto :eof

call :log "CMD START: \"%MAMBA_ENV_PY%\" -m ensurepip --upgrade"
"%MAMBA_ENV_PY%" -m ensurepip --upgrade >>"%RUNTIME_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :log "CMD END rc=!RC!"
if not "!RC!"=="0" goto :eof

call :log "CMD START: \"%MAMBA_ENV_PY%\" -m pip --version"
"%MAMBA_ENV_PY%" -m pip --version >>"%RUNTIME_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :log "CMD END rc=!RC!"
goto :eof

:cleanup_mamba_prefix
set "CLEAN_ROOT=%~1"
set "CLEAN_ENV=%~2"
if not defined CLEAN_ROOT set "CLEAN_ROOT=%MAMBA_ROOT_PREFIX%"
if not defined CLEAN_ENV set "CLEAN_ENV=%MAMBA_ENV_PREFIX%"
set "MAMBA_CLEAN_PS=%TMP%\cleanup_mamba.ps1"
>"%MAMBA_CLEAN_PS%" echo $ErrorActionPreference = 'Continue'
>>"%MAMBA_CLEAN_PS%" echo $paths = @('%CLEAN_ENV%', '%CLEAN_ROOT%\pkgs')
>>"%MAMBA_CLEAN_PS%" echo foreach ^($p in $paths^) { if ^(Test-Path $p^) { Remove-Item $p -Recurse -Force -ErrorAction Continue } }
call :log "CMD START: powershell -NoProfile -ExecutionPolicy Bypass -File \"%MAMBA_CLEAN_PS%\""
powershell -NoProfile -ExecutionPolicy Bypass -File "%MAMBA_CLEAN_PS%" >>"%RUNTIME_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :log "CMD END rc=!RC!"
goto :eof

:enable_occ_overlay
if not "%USING_MAMBA_RUNTIME%"=="1" goto :eof
if "%OCC_OVERLAY_ENABLED%"=="1" goto :eof
if not defined MAMBA_ENV_PREFIX goto :eof

call :prepare_occ_overlay
if not "%RC%"=="0" (
  call :log "ERROR: Failed to prepare OCC overlay package path."
  goto :eof
)

if defined PYTHONPATH (
  set "PYTHONPATH=%OCC_OVERLAY_SITE%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%OCC_OVERLAY_SITE%"
)

set "OCC_OVERLAY_ENABLED=1"
call :check_occ "%VENV_PY%"
if "!BREP_IMPORT_OK!"=="1" (
  call :log "INFO: Enabled OCC overlay for app runtime (no DLL PATH injection): %OCC_OVERLAY_SITE%"
  goto :eof
)

call :log "WARN: OCC import failed with package overlay only. Retrying with OCC DLL PATH injection."
set "PATH=%PATH%;%MAMBA_ENV_PREFIX%;%MAMBA_ENV_PREFIX%\Library\bin;%MAMBA_ENV_PREFIX%\DLLs;%MAMBA_ENV_PREFIX%\Scripts"
call :check_occ "%VENV_PY%"
if "!BREP_IMPORT_OK!"=="1" (
  call :log "INFO: Enabled OCC overlay with DLL PATH injection."
  goto :eof
)

call :log "ERROR: OCC overlay could not be enabled for app runtime."
goto :eof

:prepare_occ_overlay
set "RC=1"
if not defined MAMBA_ENV_PREFIX goto :eof
set "OCC_SRC=%MAMBA_ENV_PREFIX%\Lib\site-packages\OCC"
if not exist "%OCC_SRC%" (
  call :log "ERROR: OCC source package path not found: %OCC_SRC%"
  goto :eof
)
if not exist "%OCC_OVERLAY_SITE%" mkdir "%OCC_OVERLAY_SITE%"
if not exist "%OCC_OVERLAY_SITE%\OCC" mkdir "%OCC_OVERLAY_SITE%\OCC"

call :log "CMD START: robocopy \"%OCC_SRC%\" \"%OCC_OVERLAY_SITE%\OCC\" /E"
robocopy "%OCC_SRC%" "%OCC_OVERLAY_SITE%\OCC" /E /NFL /NDL /NJH /NJS /NC /NS >nul
set "RC=%ERRORLEVEL%"
call :log "CMD END rc=%RC%"
if !RC! GEQ 8 (
  set "RC=1"
  goto :eof
)
set "RC=0"
goto :eof

:accept_python_312
set "CAND_EXE=%~1"
if not defined CAND_EXE goto :eof
if not exist "%CAND_EXE%" goto :eof
"%CAND_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>&1
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

:check_occ
set "BREP_IMPORT_OK=0"
"%~1" -c "import OCC.Core" >nul 2>&1
if not errorlevel 1 set "BREP_IMPORT_OK=1"
goto :eof

:log
>>"%RUNTIME_LOG%" echo [%DATE% %TIME%] %*
goto :eof
