@echo off
rem Builds and flashes the Model 100 firmware with the MusicLEDs plugin.
rem Close Chrysalis and the visualizer first. Usage: flash.bat [COMport]
rem Needs arduino-cli with the keyboardio:gd32 core (see README).
set PORT=%1
if "%PORT%"=="" set PORT=COM5
cd /d "%~dp0"
set CLI=..\tools\arduino-cli\arduino-cli.exe
if not exist "%CLI%" set CLI=arduino-cli
set PY=..\app\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
"%CLI%" compile --fqbn keyboardio:gd32:keyboardio_model_100 --output-dir build Model100 || exit /b 1
"%PY%" flash_wait.py %PORT%
