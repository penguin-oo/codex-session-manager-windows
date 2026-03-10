@echo off
setlocal
cd /d "%~dp0"

set "TAILSCALE_IPN=C:\Program Files\Tailscale\tailscale-ipn.exe"
if exist "%TAILSCALE_IPN%" (
    tasklist /FI "IMAGENAME eq tailscale-ipn.exe" | find /I "tailscale-ipn.exe" >nul
    if errorlevel 1 start "" "%TAILSCALE_IPN%"
)

python mobile_portal.py
if not errorlevel 1 goto :eof

echo.
echo Failed to start with python, trying py launcher...
py -3 mobile_portal.py
if not errorlevel 1 goto :eof

echo.
echo Failed to start mobile portal.
echo Please ensure Python 3.11+ is installed and available in PATH.
pause
exit /b 1
