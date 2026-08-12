@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === LoL Clip Lab (local test edition) ===
echo.

rem Prefer the Windows 'py' launcher, fall back to 'python'
where py >nul 2>nul && (set "PY=py") || (set "PY=python")

%PY% bootstrap.py
if errorlevel 1 (
  echo.
  echo Setup did not finish cleanly. Read the messages above.
  pause
  exit /b 1
)

set "VENVPY=.venv\Scripts\python.exe"

rem If you dragged a VOD onto this .bat, analyze it now.
if not "%~1"=="" (
  echo.
  echo === Analyzing "%~1" ===
  "%VENVPY%" -m clip_lab analyze "%~1"
  echo.
  echo Done. Look in the *_clips folder next to your VOD for edit_sheet.md
)

echo.
echo Tip: drag-and-drop a VOD file onto START.bat to analyze it, or run:
echo     .venv\Scripts\python -m clip_lab analyze "C:\path\to\your_vod.mp4"
echo.
pause
