@echo off
setlocal
cd /d "%~dp0"
title LoL AI Master Orchestrator V4

rem Prefer the py launcher (ships with python.org installs); the bare
rem "python" name can be shadowed by the Microsoft Store stub.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 bootstrap.py %*
  goto :end
)
where python >nul 2>nul
if %errorlevel%==0 (
  python bootstrap.py %*
  goto :end
)
echo.
echo [FEHLER] Python wurde nicht gefunden.
echo Bitte Python 3.10+ von https://python.org installieren
echo (beim Installer "Add python.exe to PATH" anhaken) und START.bat erneut ausfuehren.
echo.

:end
echo.
pause
