@echo off
rem ================================================================
rem  Start Jellyfin -> JRiver Bridge Tray App (visible console)
rem  Use this for troubleshooting — shows startup output and errors.
rem ================================================================
pushd "%~dp0"
title Jellyfin to JRiver Bridge

echo ===================================================
echo   Jellyfin to JRiver Media Center Bridge
echo   Starting System Tray Application...
echo ===================================================
echo.

set "PY_CMD="
python.exe -c "exit(0)" >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python.exe"
) else (
    py.exe -c "exit(0)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py.exe"
)

if not defined PY_CMD (
    echo [ERROR] Python was not found in your PATH!
    echo         Please ensure Python 3.10+ is installed,
    echo         or run JRiverCastBridge.exe from dist\.
    echo.
    pause
    popd
    exit /b 1
)

%PY_CMD% run_tray.py

echo.
if errorlevel 1 (
    echo [ERROR] The application exited with error code: %errorlevel%
)
echo.
echo Press any key to close this window...
pause >nul
popd
