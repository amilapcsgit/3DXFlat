@echo off
setlocal

cd /d "%~dp0"

echo Launching 3DXFlat (Qt-first, Tk fallback)...
set "THREEDXFLAT_FORCE_TK=0"
python main.py
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo 3DXFlat exited with code %EXIT_CODE%.
)

exit /b %EXIT_CODE%
