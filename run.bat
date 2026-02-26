@echo off
setlocal
cd /d "%~dp0"

python app.py
if not errorlevel 1 goto :eof

echo.
echo Failed to start with python, trying py launcher...
py -3 app.py
if not errorlevel 1 goto :eof

echo.
echo Failed to start application.
echo Please ensure Python is installed and available in PATH.
pause
exit /b 1
