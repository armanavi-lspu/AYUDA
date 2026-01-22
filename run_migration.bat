@echo off
REM Activate virtual environment and run migration

echo ============================================================
echo Document Upload Workflow Migration
echo ============================================================
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo Error: Virtual environment not found at .venv\Scripts\activate.bat
    echo Please ensure your virtual environment is set up correctly.
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Run migration
echo.
echo Running migration script...
python run_migration_flask.py

REM Deactivate when done
call .venv\Scripts\deactivate.bat

echo.
echo ============================================================
echo Migration process complete!
echo ============================================================
echo.
pause
