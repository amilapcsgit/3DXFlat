@echo off
setlocal

cd /d "%~dp0"

call "%~dp03DXFlat.bat"
exit /b %ERRORLEVEL%
