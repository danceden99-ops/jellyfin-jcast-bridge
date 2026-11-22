@echo off
setlocal enabledelayedexpansion
pushd "%~dp0"
title Build JRiverCastBridge Standalone Executable

echo ================================================================
echo   Building JRiverCastBridge.exe (PyInstaller Single-File Executable)
echo ================================================================
echo.

rem 1. Find working Python
set "PY_CMD="
python.exe -c "exit(0)" >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python.exe"
) else (
    py.exe -c "exit(0)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py.exe"
)

if not defined PY_CMD (
    echo [ERROR] No Python installation found in PATH!
    echo         Please ensure Python is installed and in your PATH.
    echo.
    pause
    popd
    exit /b 1
)

echo [1/3] Checking PyInstaller...
!PY_CMD! -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo       PyInstaller not found. Installing via pip...
    !PY_CMD! -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller. Check your internet connection.
        pause
        popd
        exit /b 1
    )
) else (
    echo       PyInstaller is already installed.
)

echo.
echo [2/3] Compiling standalone executable with PyInstaller...
!PY_CMD! -m PyInstaller JRiverCastBridge.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller compilation failed! Check error messages above.
    pause
    popd
    exit /b 1
)

echo.
echo [3/3] Preparing release folder (dist\)...
if exist "%~dp0config.yaml" (
    copy /Y "%~dp0config.yaml" "%~dp0dist\config.yaml" >nul
    echo       Copied config.yaml into dist\
) else if exist "%~dp0config.example.yaml" (
    copy /Y "%~dp0config.example.yaml" "%~dp0dist\config.yaml" >nul
    echo       Copied config.example.yaml as dist\config.yaml
)
if not exist "%~dp0dist\certs" mkdir "%~dp0dist\certs"
if exist "%~dp0certs\cast_bridge.crt" (
    copy /Y "%~dp0certs\*.*" "%~dp0dist\certs\" >nul
    echo       Copied existing certs into dist\certs\
)

echo.
echo ================================================================
echo   SUCCESS! Standalone executable generated at:
echo   %~dp0dist\JRiverCastBridge.exe
echo.
echo   To deploy:
echo   Copy "dist\JRiverCastBridge.exe" and "dist\config.yaml" to
echo   ANY directory on your PC. No Python installation required!
echo ================================================================
echo.
pause
popd
