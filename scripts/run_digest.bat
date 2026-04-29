@echo off
REM IdeaScout weekly digest wrapper. Day 3 will populate the actual digest
REM generator; this stub ensures Task Scheduler can be wired now and
REM activated later by editing only the digest command, not the schedule.

setlocal

set "ROOT=%~dp0.."
set "LOG_DIR=%ROOT%\data\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "usebackq" %%i in (`powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"`) do set "STAMP=%%i"
set "LOG=%LOG_DIR%\%STAMP%-digest.log"
set "PYTHONIOENCODING=utf-8"

cd /d "%ROOT%"

echo === Digest run started %DATE% %TIME% === >> "%LOG%"
py -3.13 -m ideascout digest >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
if %RC% EQU 0 (
  py -3.13 -m ideascout dashboard >> "%LOG%" 2>&1
  set "RC=%ERRORLEVEL%"
)
echo === Digest run finished %DATE% %TIME% rc=%RC% === >> "%LOG%"

endlocal
exit /b %RC%
