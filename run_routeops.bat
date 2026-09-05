@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta install_and_run.bat
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
start "" http://127.0.0.1:5000
python app.py
endlocal
