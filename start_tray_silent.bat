@echo off
rem ================================================================
rem  Start Jellyfin -> JRiver Bridge Tray App (silent, no console)
rem ================================================================
pushd "%~dp0"
if exist "%~dp0start_tray_silent.vbs" (
    start "" wscript.exe "%~dp0start_tray_silent.vbs"
) else (
    start "" /d "%~dp0" pythonw.exe "%~dp0run_tray.py"
)
popd
