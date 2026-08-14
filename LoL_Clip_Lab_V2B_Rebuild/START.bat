@echo off
rem =====================================================================
rem  LoL Clip Lab — Windows-Launcher
rem    Doppelklick            = Setup + Selbsttest
rem    VOD-DATEI draufziehen  = analyze
rem    ORDNER draufziehen     = batch
rem  Bewusst OHNE enabledelayedexpansion (frisst ! in Dateinamen) und
rem  OHNE if-Klammer-Bloecke (Klammern in Pfaden crashen den cmd-Parser).
rem  Diese Datei braucht CRLF-Zeilenenden (GOTO/CALL-Labels!).
rem =====================================================================
setlocal
cd /d "%~dp0"

rem Python finden: "python" probieren (der Store-Stub exitet mit Fehler),
rem sonst den py-Launcher von python.org nutzen.
set "PYCMD=python"
python -c "" >nul 2>nul
if errorlevel 1 set "PYCMD=py -3"

set "PYEXE=.venv\Scripts\python.exe"
if exist "%PYEXE%" goto HAVEPY
set "PYEXE=%PYCMD%"

:HAVEPY
if "%~1"=="" goto SETUP
if exist "%~1\*" goto BATCHMODE
if exist "%~1" goto FILEMODE

echo Datei oder Ordner nicht gefunden: "%~1"
pause
exit /b 2

:SETUP
echo === LoL Clip Lab: Setup + Selbsttest ===
%PYCMD% bootstrap.py
echo.
pause
exit /b 0

:FILEMODE
if not exist ".venv\Scripts\python.exe" call :ENSURE
echo === Analysiere VOD: "%~1" ===
%PYEXE% -m cliplab analyze "%~1"
echo.
pause
exit /b %errorlevel%

:BATCHMODE
if not exist ".venv\Scripts\python.exe" call :ENSURE
echo === Batch-Analyse: "%~1" ===
%PYEXE% -m cliplab batch "%~1"
echo.
pause
exit /b %errorlevel%

:ENSURE
echo Erststart erkannt - richte zuerst die Umgebung ein ...
%PYCMD% bootstrap.py
set "PYEXE=.venv\Scripts\python.exe"
if exist "%PYEXE%" exit /b 0
set "PYEXE=%PYCMD%"
exit /b 0
