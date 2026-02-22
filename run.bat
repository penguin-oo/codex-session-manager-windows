@echo off
setlocal
cd /d %~dp0
py -3 app.py
if errorlevel 1 (
  echo.
  echo Failed to start with py launcher, trying python...
  python app.py
)
endlocal
