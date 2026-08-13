@echo off
rem =====================================================================
rem  LoL Clip Lab — Windows-Launcher
rem    Doppelklick            = Setup + Selbsttest
rem    VOD-DATEI draufziehen  = analyze
rem    ORDNER draufziehen     = batch
rem  Bewusst OHNE enabledelayedexpansion (frisst ! in Dateinamen) und
rem  OHNE if-Klammer-Bloecke (Klammern in Pfaden crashen den cmd-Parser).
rem =====================================================================
setlocal
cd /d "%~dp0"

set "PYEXE=.venv\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

if "%~1"=="" goto SETUP
if exist "%~1\*" goto BATCHMODE
if exist "%~1" goto FILEMODE

echo Datei oder Ordner nicht gefunden: "%~1"
pause
exit /b 2

:SETUP
echo === LoL Clip Lab: Setup + Selbsttest ===
python bootstrap.py
echo.
pause
exit /b 0

:FILEMODE
if not exist ".venv\Scripts\python.exe" call :ENSURE
echo === Analysiere VOD: "%~1" ===
"%PYEXE%" -m cliplab analyze "%~1"
echo.
pause
exit /b %errorlevel%

:BATCHMODE
if not exist ".venv\Scripts\python.exe" call :ENSURE
echo === Batch-Analyse: "%~1" ===
"%PYEXE%" -m cliplab batch "%~1"
echo.
pause
exit /b %errorlevel%

:ENSURE
echo Erststart erkannt - richte zuerst die Umgebung ein ...
python bootstrap.py
set "PYEXE=.venv\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
exit /b 0
