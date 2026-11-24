@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"
set "PYTHONUTF8=1"

if /I "%~1"=="--gui" goto :launch_gui
goto :launch_cli

:launch_gui
shift
if exist "%REPO_ROOT%\.venv\Scripts\qcai-app.exe" (
    start "" "%REPO_ROOT%\.venv\Scripts\qcai-app.exe" %1 %2 %3 %4 %5 %6 %7 %8 %9
    exit /b 0
)
goto :launch_cli

:launch_cli
if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
    "%REPO_ROOT%\.venv\Scripts\python.exe" -m qcai.launcher %1 %2 %3 %4 %5 %6 %7 %8 %9
) else (
    set "UV_CMD="
    where uv >nul 2>nul
    if %errorlevel%==0 set "UV_CMD=uv"
    if not defined UV_CMD if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
    if defined UV_CMD (
        "%UV_CMD%" run python -m qcai.launcher %1 %2 %3 %4 %5 %6 %7 %8 %9
    ) else (
        echo [QuantumChem AI] Missing .venv and uv. Please run the root installer batch file first.
        pause
        exit /b 1
    )
)

if errorlevel 1 (
    echo.
    echo [QuantumChem AI] Launcher exited with code %errorlevel%.
    pause
)
