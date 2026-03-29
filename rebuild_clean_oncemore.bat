@echo off
REM ==================================================
REM  Galactic Conclave — Clean Rebuild Script
REM  Usage: rebuild_clean_oncemore.bat
REM ==================================================

cd /d "%~dp0"

echo ================================================
echo  Galactic Conclave — Clean Rebuild v2.0
echo ================================================
echo.

REM ── Check Python is available ────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.10+ from python.org or add to PATH
    pause
    exit /b 1
)
python --version

echo.
echo === STEP 1: Cleaning old build artifacts ===
echo.

if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist "*.spec" del "*.spec"
if exist build_temp rmdir /s /q build_temp
if exist dist_temp rmdir /s /q dist_temp

echo   Removed: build/
echo   Removed: dist/
echo   Removed: *.spec files
echo.

REM ── Activate virtual environment if it exists ─────────────
if exist venv\Scripts\activate.bat (
    echo === STEP 2: Activating virtual environment ===
    echo.
    call venv\Scripts\activate.bat
) else (
    echo === STEP 2: No venv found — using system Python ===
    echo.
)

REM ── Install/update dependencies ───────────────────────────
echo === STEP 3: Installing dependencies ===
echo.
echo This may take a minute...
pip install --upgrade pyinstaller
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    echo Check your internet connection and try again
    pause
    exit /b 1
)
echo.

REM ── Ensure README exists ───────────────────────────────────
if not exist README.md (
    (
        echo # Galactic Conclave
        echo.
        echo Stellaris AI Empire Chat Overlay
        echo.
        echo See WORKSHOP_DESCRIPTION.txt for details.
    ) > README.md
    echo Created README.md
) else (
    echo README.md already exists
)
echo.

REM ── Build executable ──────────────────────────────────────
echo === STEP 4: Building GalacticConclave.exe ===
echo.
echo Building with PyInstaller...

set HIDDEN=--hidden-import config ^
           --hidden-import prompts ^
           --hidden-import llm_client ^
           --hidden-import save_parser ^
           --hidden-import game_io ^
           --hidden-import ui

if exist WORKSHOP_DESCRIPTION.txt (
    echo Including WORKSHOP_DESCRIPTION.txt
    python -m PyInstaller ^
        --onefile ^
        --windowed ^
        --name GalacticConclave ^
        --add-data "README.md;." ^
        --add-data "WORKSHOP_DESCRIPTION.txt;." ^
        %HIDDEN% ^
        main.py
) else (
    echo WARNING: WORKSHOP_DESCRIPTION.txt not found — building without it
    python -m PyInstaller ^
        --onefile ^
        --windowed ^
        --name GalacticConclave ^
        --add-data "README.md;." ^
        %HIDDEN% ^
        main.py
)

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed
    echo Check the errors above for details
    pause
    exit /b 1
)

echo.

REM ── Verify build success ───────────────────────────────────
echo === STEP 5: Verifying build ===
echo.
if exist dist\GalacticConclave.exe (
    echo ==================================================
    echo BUILD SUCCESSFUL!
    echo ==================================================
    echo.
    echo Output: dist\GalacticConclave.exe
    echo.
    echo You can now copy this file to your game directory
    echo or share it as needed.
    echo.
    echo To run: dist\GalacticConclave.exe
    echo.
) else (
    echo ==================================================
    echo BUILD FAILED
    echo ==================================================
    echo.
    echo Executable not found at dist\GalacticConclave.exe
    echo Check the errors above for details
    echo.
    pause
    exit /b 1
)

echo.
echo All done! Press any key to exit...
pause >nul
