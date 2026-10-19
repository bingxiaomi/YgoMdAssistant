@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Please create .venv and install requirements.lock first. See README.md.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0run.py"
