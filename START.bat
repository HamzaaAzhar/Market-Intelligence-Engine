@echo off
title Scraper Intelligence System
color 0A
echo.
echo  ============================================
echo   SCRAPER INTELLIGENCE SYSTEM
echo  ============================================
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found.
    echo  Install from https://www.python.org/downloads/
    echo  Check "Add Python to PATH" during install.
    pause & exit /b 1
)
echo  Installing dependencies...
pip install flask requests beautifulsoup4 --quiet --disable-pip-version-check
echo  Starting server...
echo  Browser will open automatically.
echo  Press Ctrl+C to stop.
echo  ============================================
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:5000"
python app.py
pause
