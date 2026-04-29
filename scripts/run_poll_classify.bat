@echo off
REM IdeaScout daily wrapper. Polls all enabled sources, then classifies
REM the new posts via local Ollama. Logs to data\logs\YYYY-MM-DD-poll-classify.log.
REM
REM Designed to be invoked by Windows Task Scheduler. Exit code 0 on success,
REM non-zero on failure (the scheduler retries per the registered settings).

setlocal

set "ROOT=%~dp0.."
set "LOG_DIR=%ROOT%\data\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Locale-safe date stamp via PowerShell.
for /f "usebackq" %%i in (`powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"`) do set "STAMP=%%i"

set "LOG=%LOG_DIR%\%STAMP%-poll-classify.log"

REM Force UTF-8 in Python so non-ASCII titles (Pew, etc.) don't crash logging.
set "PYTHONIOENCODING=utf-8"

cd /d "%ROOT%"

echo === Run started %DATE% %TIME% === >> "%LOG%"

py -3.13 -m ideascout poll >> "%LOG%" 2>&1
if errorlevel 1 (
  echo POLL FAILED with errorlevel %ERRORLEVEL% >> "%LOG%"
  endlocal
  exit /b 1
)

py -3.13 -m ideascout classify --quiet >> "%LOG%" 2>&1
if errorlevel 1 (
  echo CLASSIFY FAILED with errorlevel %ERRORLEVEL% >> "%LOG%"
  endlocal
  exit /b 1
)

echo === Run finished %DATE% %TIME% === >> "%LOG%"
endlocal
exit /b 0
