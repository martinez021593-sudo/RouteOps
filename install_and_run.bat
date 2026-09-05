@echo off
setlocal
cd /d "%~dp0"
echo.
echo ==========================================
echo   RouteOps V0.3 - Instalacion / Arranque
echo ==========================================
echo.
where py >nul 2>&1
if %errorlevel%==0 (
  set PY=py
) else (
  set PY=python
)
if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno virtual...
  %PY% -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
start "" http://127.0.0.1:5000
python app.py
endlocal
