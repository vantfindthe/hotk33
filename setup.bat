@echo off
rem One-time setup: creates .venv and installs the dependencies.
cd /d "%~dp0"
py -3.12 -m venv .venv || python -m venv .venv || goto :error
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt || goto :error
echo.
echo Done. Start Predictive Key Lights with KeyLights.bat
exit /b 0
:error
echo Setup failed - is Python 3.12 installed? https://www.python.org/downloads/
exit /b 1
