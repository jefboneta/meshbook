@echo off
setlocal

set REPO=https://raw.githubusercontent.com/jefboneta/meshbook/main
set INSTALL_DIR=%USERPROFILE%\meshbook

echo MeshBook installer
echo ===================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python not found. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)

python --version

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
cd /d "%INSTALL_DIR%"

echo.
echo Installing dependencies...
curl -fsSL "%REPO%/requirements.txt" -o requirements.txt
python -m pip install --user --quiet -r requirements.txt

echo.
echo Downloading meshbook.py...
curl -fsSL "%REPO%/meshbook.py" -o meshbook.py
curl -fsSL "%REPO%/README.md" -o README.md

echo.
echo ===================
echo Installed to: %INSTALL_DIR%
echo.
echo Set MESHBOOK_MQTT_USER and MESHBOOK_MQTT_PASS before launching.
echo To run:
echo   cd %INSTALL_DIR%
echo   python meshbook.py
echo.

pause
