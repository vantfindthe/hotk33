@echo off
rem Starts Hotk33 (no console window). Run setup.bat once first.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app\app.py"
