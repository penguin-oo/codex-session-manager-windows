@echo off
setlocal
cd /d "%~dp0"

set "ELEVATE_ARGS=%*"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent()); if ($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges for the mobile portal...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%ComSpec%' -Verb RunAs -WorkingDirectory '%~dp0' -ArgumentList '/c','\"\"%~f0\"\" %ELEVATE_ARGS%'" >nul 2>&1
    if errorlevel 1 (
        echo Administrator elevation was canceled.
        pause
    )
    exit /b
)

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
