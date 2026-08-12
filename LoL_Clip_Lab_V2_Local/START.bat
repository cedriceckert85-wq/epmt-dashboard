@echo off
rem plain setlocal: delayed expansion would eat "!" in dragged paths like
rem "CRAZY PENTA!!!.mp4" (no !var! expansion is used anywhere in this script)
setlocal
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

rem Dragged something onto this .bat? A folder -> batch-analyze everything in
rem it - the channel memory grows across all videos. A file -> analyze it.
rem NOTE: no unescaped parentheses inside this block - a bare ")" in an echo
rem would terminate the if-block early and kill the whole script.
if not "%~1"=="" (
  echo.
  if exist "%~1\" (
    echo === Batch-analyzing folder "%~1" ===
    "%VENVPY%" -m clip_lab batch "%~1"
  ) else (
    echo === Analyzing "%~1" ===
    "%VENVPY%" -m clip_lab analyze "%~1"
  )
  echo.
  echo Done. Look in the *_clips folders next to your videos for edit_sheet.md
)

echo.
echo Tips:
echo   - drag a VOD file onto START.bat to analyze it
echo   - drag a FOLDER of VODs onto START.bat to analyze them all
echo   - put example clips you like into references\ and run:
echo         .venv\Scripts\python -m clip_lab learn
echo.
pause
