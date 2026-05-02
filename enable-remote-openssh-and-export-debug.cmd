@echo off
setlocal
set "SCRIPT=%~dp0enable-remote-openssh-and-export-debug.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','''%SCRIPT%'''"
endlocal
