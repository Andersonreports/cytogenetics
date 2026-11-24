@echo off
rem Start the CMC Cytogenetics report tool and open it in the browser.
rem   run.bat          this computer only
rem   run.bat --lan    also reachable from other computers on the office network
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m backend.main %*
) else (
    python -m backend.main %*
)
if errorlevel 1 pause
